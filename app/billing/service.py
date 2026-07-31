"""BillingService -- the single centralized place every subscription
lifecycle rule lives, matching app.analytics.service.AnalyticsService's
exact "thin routers, one service class" style. No router or job ever
mutates a Subscription row directly; every state change goes through a
method here, and every mutating method writes exactly one (or two, for
create_subscription's create+trial-start pair) SubscriptionEvent row in
the same transaction as its own commit -- this is what makes
SubscriptionEvent a trustworthy history rather than a best-effort log.

Plan comparisons (upgrade vs. downgrade) are always by Plan.sort_order,
never by plan code or name -- the one rule this whole domain is built
around (see this phase's own spec: never write `if plan == "pro"`).

Phase 18 adds a `provider` field (an app.billing.provider_base
.BillingProvider) and the checkout/webhook-sync methods at the bottom of
this class -- BillingService depends only on that abstraction, never on
a concrete provider's SDK or wire format (see app.billing.provider_base's
own module docstring). Every method ABOVE that section is unchanged from
Phase 17A/17B: pure-DB lifecycle transitions with no provider awareness
at all, and every existing call site (`BillingService(db)`, with no
`provider` argument) keeps behaving exactly as before, since `provider`
defaults to NullBillingProvider -- see that class's own docstring for why
that default fails closed rather than silently no-oping.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.billing.null_provider import NullBillingProvider
from app.billing.provider_base import (
    BillingProvider,
    BillingProviderEventType,
    CheckoutSessionRequest,
    ProviderCheckoutSession,
    ProviderPortalSession,
    ProviderWebhookEvent,
)
from app.billing_period import BillingPeriod
from app.models import Plan, ProviderCustomer, Subscription, SubscriptionEvent, User
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus

# Deliberately simple fixed-length periods (30/365 days), not calendar-
# month/year arithmetic -- this phase has no payment provider driving
# real billing-cycle dates, so a plain, predictable length is honest
# about what's actually being modeled (a future provider integration is
# what would replace this with real calendar-anchored billing).
_PERIOD_LENGTH: dict[BillingPeriod, timedelta] = {
    BillingPeriod.monthly: timedelta(days=30),
    BillingPeriod.yearly: timedelta(days=365),
}


class InvalidPlanChangeError(Exception):
    """Raised when upgrade_plan/downgrade_plan is called with a plan that
    doesn't actually move in the requested direction (by sort_order) --
    fails closed rather than silently recording a mislabeled event."""


class InvalidSubscriptionStateError(Exception):
    """Raised when a lifecycle method is called on a subscription in a
    state that operation doesn't apply to (e.g. resume() on a
    subscription that isn't paused) -- fails closed rather than
    silently producing an inconsistent state + a misleading event."""


class SubscriptionConflictError(Exception):
    """Raised by _commit when a concurrent writer already advanced this
    Subscription's `version` between when this call loaded it and when
    it tried to commit -- the domain-level translation of the
    StaleDataError SQLAlchemy's version_id_col mapper feature raises
    (see Subscription's own docstring in app.models). This is exactly
    the "two mutations racing on the same subscription" case Phase P2.1
    hardens: a Stripe webhook and a platform-admin action (or two
    webhooks, or two admin actions) each loading the same row and
    racing to commit a change. Every router that can reach a
    BillingService mutation maps this to a stable 409 response --
    never retried automatically here or by any caller in this module,
    since the subscription's true current state may have moved in a
    way that makes blindly repeating the same mutation wrong (e.g. a
    webhook's cancel racing an admin's plan change: re-applying the
    cancel after the plan change without re-reading first would step on
    it silently -- the same lost-update bug this whole mechanism exists
    to prevent, just one layer up)."""

    def __init__(self, message: str, *, current_version: int | None = None):
        super().__init__(message)
        self.current_version = current_version


def _period_length(billing_period: str) -> timedelta:
    return _PERIOD_LENGTH[BillingPeriod(billing_period)]


@dataclass(frozen=True)
class BillingService:
    """Bound only to a Session, not to one organization -- unlike
    AnalyticsService (always scoped to a single org's own read-only
    metrics), BillingService's callers include platform-admin operations
    that act on an arbitrary organization's subscription, so the target
    subscription/organization is always an explicit argument to each
    method rather than baked into the instance."""

    db: Session
    provider: BillingProvider = field(default_factory=NullBillingProvider)

    # --- internal helpers -------------------------------------------

    def _record_event(
        self,
        subscription: Subscription,
        *,
        event_type: SubscriptionEventType,
        actor: User | None = None,
        previous_values: dict | None = None,
        new_values: dict | None = None,
        metadata: dict | None = None,
    ) -> SubscriptionEvent:
        event = SubscriptionEvent(
            organization_id=subscription.organization_id,
            subscription_id=subscription.id,
            actor_user_id=actor.id if actor is not None else None,
            event_type=event_type.value,
            previous_values=json.dumps(previous_values) if previous_values is not None else None,
            new_values=json.dumps(new_values) if new_values is not None else None,
            metadata_json=json.dumps(metadata) if metadata is not None else None,
        )
        self.db.add(event)
        return event

    def _commit(self, subscription: Subscription) -> Subscription:
        """Commits whatever ORM-attribute mutations the caller already
        made to `subscription` -- version_id_col (see Subscription's own
        docstring) makes this flush's UPDATE conditional on the version
        this instance was loaded with, so a StaleDataError here means
        another writer's commit already won the race. That's translated
        to SubscriptionConflictError rather than left to leak a
        SQLAlchemy-specific exception type past this class's own
        boundary -- every caller of a BillingService method should only
        ever need to know this module's own vocabulary."""
        try:
            self.db.commit()
        except StaleDataError as exc:
            self.db.rollback()
            current = self.db.get(Subscription, subscription.id)
            raise SubscriptionConflictError(
                f"Subscription {subscription.id!r} was concurrently modified by another "
                "process; reload and retry.",
                current_version=current.version if current is not None else None,
            ) from exc
        self.db.refresh(subscription)
        return subscription

    # --- creation & trial lifecycle -----------------------------------

    def create_subscription(
        self,
        organization_id: str,
        plan_id: str,
        *,
        billing_period: BillingPeriod = BillingPeriod.monthly,
        trial_days: int = 0,
        actor: User | None = None,
        provider_name: str | None = None,
        provider_reference: str | None = None,
    ) -> Subscription:
        """Creates the one Subscription an organization owns -- called
        from app.routers.auth.register at signup (trial_days=0 for the
        Free plan; a future provider-aware signup flow could pass a real
        trial length for a paid plan). status=trialing when trial_days>0,
        else active straight away.

        `provider_name`/`provider_reference` are optional and default to
        None, exactly as every pre-Phase-18 call site already expects --
        passing neither (the only way app.routers.auth.register calls
        this today) produces byte-for-byte the same row and the same
        subscription_created event.new_values dict as before Phase 18.
        Only a provider-driven creation flow (not built by any router
        yet; see attach_provider_subscription for attaching a provider to
        an EXISTING subscription instead, which is what
        sync_from_webhook_event actually uses) would pass them here."""
        now = datetime.now(timezone.utc)
        is_trial = trial_days > 0
        status = SubscriptionStatus.trialing if is_trial else SubscriptionStatus.active

        subscription = Subscription(
            organization_id=organization_id,
            plan_id=plan_id,
            status=status.value,
            billing_period=billing_period.value,
            trial_start=now if is_trial else None,
            trial_end=now + timedelta(days=trial_days) if is_trial else None,
            current_period_start=now,
            current_period_end=now + _period_length(billing_period.value),
            provider_name=provider_name,
            provider_reference=provider_reference,
        )
        self.db.add(subscription)
        self.db.flush()

        new_values = {
            "plan_id": plan_id,
            "status": status.value,
            "billing_period": billing_period.value,
        }
        if provider_name is not None:
            new_values["provider_name"] = provider_name
        if provider_reference is not None:
            new_values["provider_reference"] = provider_reference
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_created,
            actor=actor,
            new_values=new_values,
        )
        if is_trial:
            self._record_event(
                subscription,
                event_type=SubscriptionEventType.trial_started,
                actor=actor,
                new_values={"trial_end": subscription.trial_end.isoformat()},
            )
        return self._commit(subscription)

    def start_trial(
        self, subscription: Subscription, *, trial_days: int, actor: User | None = None
    ) -> Subscription:
        """Starts (or restarts) a trial on an EXISTING subscription --
        distinct from create_subscription's own trial_days, which only
        applies at the moment of first creation. Used for e.g. a platform
        admin granting a trial of a higher plan to an already-subscribed
        organization."""
        if trial_days <= 0:
            raise InvalidSubscriptionStateError("trial_days must be positive")
        previous_status = subscription.status
        now = datetime.now(timezone.utc)
        subscription.status = SubscriptionStatus.trialing.value
        subscription.trial_start = now
        subscription.trial_end = now + timedelta(days=trial_days)
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.trial_started,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status, "trial_end": subscription.trial_end.isoformat()},
        )
        return self._commit(subscription)

    def expire_trial(self, subscription: Subscription, *, actor: User | None = None) -> Subscription:
        """A trial's trial_end has passed with no conversion to active --
        moves straight to `expired` (there is no payment provider in this
        phase to attempt a charge and fall back from), distinct from
        expire_subscription's more general "this subscription has run its
        course" case below."""
        if subscription.status != SubscriptionStatus.trialing.value:
            raise InvalidSubscriptionStateError(
                f"Cannot expire a trial on a subscription with status {subscription.status!r}"
            )
        previous_status = subscription.status
        subscription.status = SubscriptionStatus.expired.value
        subscription.ended_at = datetime.now(timezone.utc)
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.trial_expired,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status},
        )
        return self._commit(subscription)

    def activate_subscription(
        self, subscription: Subscription, *, actor: User | None = None
    ) -> Subscription:
        """Moves a subscription to `active` -- most commonly a trial that
        converted, but also usable from `inactive`/`paused`. A no-op
        (still returns the row, no event written) if already active, so
        callers never have to check status first."""
        if subscription.status == SubscriptionStatus.active.value:
            return subscription
        previous_status = subscription.status
        subscription.status = SubscriptionStatus.active.value
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_activated,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status},
        )
        return self._commit(subscription)

    # --- plan & billing-period changes ---------------------------------

    def _change_plan(
        self,
        subscription: Subscription,
        new_plan: Plan,
        *,
        actor: User | None,
        event_type: SubscriptionEventType | None = None,
        require_sort_order: str | None = None,
    ) -> Subscription:
        current_plan = self.db.get(Plan, subscription.plan_id)
        if current_plan is None:
            raise InvalidPlanChangeError(
                f"Subscription's current plan_id {subscription.plan_id!r} does not exist"
            )
        if require_sort_order == "higher" and new_plan.sort_order <= current_plan.sort_order:
            raise InvalidPlanChangeError(
                f"{new_plan.code!r} (sort_order={new_plan.sort_order}) is not an upgrade from "
                f"{current_plan.code!r} (sort_order={current_plan.sort_order})"
            )
        if require_sort_order == "lower" and new_plan.sort_order >= current_plan.sort_order:
            raise InvalidPlanChangeError(
                f"{new_plan.code!r} (sort_order={new_plan.sort_order}) is not a downgrade from "
                f"{current_plan.code!r} (sort_order={current_plan.sort_order})"
            )

        resolved_event_type = event_type
        if resolved_event_type is None:
            if new_plan.sort_order > current_plan.sort_order:
                resolved_event_type = SubscriptionEventType.plan_upgraded
            elif new_plan.sort_order < current_plan.sort_order:
                resolved_event_type = SubscriptionEventType.plan_downgraded
            else:
                resolved_event_type = SubscriptionEventType.manual_adjustment

        old_plan_id = subscription.plan_id
        subscription.plan_id = new_plan.id
        self._record_event(
            subscription,
            event_type=resolved_event_type,
            actor=actor,
            previous_values={"plan_id": old_plan_id, "plan_code": current_plan.code},
            new_values={"plan_id": new_plan.id, "plan_code": new_plan.code},
        )
        return self._commit(subscription)

    def upgrade_plan(
        self, subscription: Subscription, new_plan: Plan, *, actor: User | None = None
    ) -> Subscription:
        """Moves to a plan with a HIGHER sort_order than the current one
        -- classified by that comparison alone, never by plan code/name
        (see this module's own docstring)."""
        return self._change_plan(
            subscription,
            new_plan,
            actor=actor,
            event_type=SubscriptionEventType.plan_upgraded,
            require_sort_order="higher",
        )

    def downgrade_plan(
        self, subscription: Subscription, new_plan: Plan, *, actor: User | None = None
    ) -> Subscription:
        """Moves to a plan with a LOWER sort_order than the current one."""
        return self._change_plan(
            subscription,
            new_plan,
            actor=actor,
            event_type=SubscriptionEventType.plan_downgraded,
            require_sort_order="lower",
        )

    def change_plan(
        self, subscription: Subscription, new_plan: Plan, *, actor: User | None = None
    ) -> Subscription:
        """Reassigns a subscription to any active plan regardless of
        sort_order direction -- the platform-admin "assign this plan"
        action (app.routers.platform_admin.update_organization_plan),
        distinct from upgrade_plan/downgrade_plan's stricter,
        direction-asserting variants meant for a tenant-initiated plan
        change. The event is classified by comparing sort_order same as
        those two methods, except a lateral move (equal sort_order,
        e.g. two custom plans an admin defined at the same tier) is
        recorded as manual_adjustment instead of raising."""
        return self._change_plan(subscription, new_plan, actor=actor)

    def change_billing_period(
        self, subscription: Subscription, new_period: BillingPeriod, *, actor: User | None = None
    ) -> Subscription:
        """Switches monthly<->yearly -- extends/shortens
        current_period_end from the existing current_period_start by the
        new period's length (no proration; see this phase's own
        non-goals). A no-op if already on the requested period."""
        if subscription.billing_period == new_period.value:
            return subscription
        previous_period = subscription.billing_period
        subscription.billing_period = new_period.value
        subscription.current_period_end = subscription.current_period_start + _period_length(
            new_period.value
        )
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.billing_period_changed,
            actor=actor,
            previous_values={"billing_period": previous_period},
            new_values={"billing_period": subscription.billing_period},
        )
        return self._commit(subscription)

    def renew(self, subscription: Subscription, *, actor: User | None = None) -> Subscription:
        """Advances the current billing period by one length, anchored on
        the previous period's own end (never "now") so a renewal
        processed a few hours late doesn't quietly shrink the next
        period."""
        length = _period_length(subscription.billing_period)
        previous_end = subscription.current_period_end
        subscription.current_period_start = previous_end
        subscription.current_period_end = previous_end + length
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_renewed,
            actor=actor,
            previous_values={"current_period_end": previous_end.isoformat()},
            new_values={"current_period_end": subscription.current_period_end.isoformat()},
        )
        return self._commit(subscription)

    # --- cancellation & resumption --------------------------------------

    def cancel_immediately(
        self, subscription: Subscription, *, actor: User | None = None
    ) -> Subscription:
        """Ends the subscription right now -- status=canceled,
        ended_at=now. Distinct from cancel_at_period_end below, which
        keeps the subscription active/trialing through its current
        period and only stops it from renewing."""
        now = datetime.now(timezone.utc)
        previous_status = subscription.status
        subscription.status = SubscriptionStatus.canceled.value
        subscription.canceled_at = now
        subscription.ended_at = now
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_canceled,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status},
            metadata={"immediate": True},
        )
        return self._commit(subscription)

    def cancel_at_period_end(
        self, subscription: Subscription, *, actor: User | None = None
    ) -> Subscription:
        """Flags the subscription to stop renewing once current_period_end
        is reached -- status/ended_at are untouched here (the
        organization keeps full access through the paid-for period); a
        future scheduled job (out of scope this phase) would be what
        actually calls cancel_immediately or expire_subscription once
        that period arrives."""
        if subscription.cancel_at_period_end:
            return subscription
        subscription.cancel_at_period_end = True
        subscription.canceled_at = datetime.now(timezone.utc)
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_canceled,
            actor=actor,
            new_values={"cancel_at_period_end": True},
            metadata={"immediate": False},
        )
        return self._commit(subscription)

    def reactivate(self, subscription: Subscription, *, actor: User | None = None) -> Subscription:
        """Undoes a cancellation -- clears cancel_at_period_end, and if
        the subscription had already reached `canceled`, brings it back
        to `active`. Raises if the subscription was never canceled at
        all, so a caller can't silently no-op on the wrong row."""
        if not subscription.cancel_at_period_end and subscription.status != SubscriptionStatus.canceled.value:
            raise InvalidSubscriptionStateError("Subscription is not canceled or pending cancellation")

        previous_status = subscription.status
        subscription.cancel_at_period_end = False
        subscription.canceled_at = None
        if subscription.status == SubscriptionStatus.canceled.value:
            subscription.status = SubscriptionStatus.active.value
            subscription.ended_at = None
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_reactivated,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status},
        )
        return self._commit(subscription)

    def resume(self, subscription: Subscription, *, actor: User | None = None) -> Subscription:
        """Resumes a `paused` subscription back to `active` -- `paused`
        exists for a future payment-provider integration (e.g. a
        provider-side hold); this phase never sets it itself, but the
        transition back out of it is implemented now so the state
        machine is complete."""
        if subscription.status != SubscriptionStatus.paused.value:
            raise InvalidSubscriptionStateError(
                f"Cannot resume a subscription with status {subscription.status!r}"
            )
        subscription.status = SubscriptionStatus.active.value
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_resumed,
            actor=actor,
            previous_values={"status": SubscriptionStatus.paused.value},
            new_values={"status": subscription.status},
        )
        return self._commit(subscription)

    def expire_subscription(
        self, subscription: Subscription, *, actor: User | None = None
    ) -> Subscription:
        """A subscription that has run its course without an explicit
        cancellation (e.g. current_period_end reached with
        cancel_at_period_end set, once a future scheduled job drives
        that transition) -- status=expired, ended_at=now. Distinct from
        expire_trial above, which is specifically for a trial that never
        converted."""
        previous_status = subscription.status
        subscription.status = SubscriptionStatus.expired.value
        subscription.ended_at = datetime.now(timezone.utc)
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.subscription_expired,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status},
        )
        return self._commit(subscription)

    # --- provider integration (Phase 18) ---------------------------------

    def get_subscription_by_provider_reference(
        self, *, provider_name: str, provider_reference: str
    ) -> Subscription | None:
        """Looks up the Subscription attached to a given provider's
        subscription id -- how app.routers.billing_webhooks resolves an
        incoming webhook event to a row, for every event type except
        checkout_completed (where no Subscription is attached to this
        provider_reference yet; see sync_from_webhook_event)."""
        return self.db.scalar(
            select(Subscription).where(
                Subscription.provider_name == provider_name,
                Subscription.provider_reference == provider_reference,
            )
        )

    def attach_provider_subscription(
        self,
        subscription: Subscription,
        *,
        provider_name: str,
        provider_reference: str,
        actor: User | None = None,
    ) -> Subscription:
        """Links an EXISTING Subscription row to a provider-side
        subscription -- called once, when a checkout_completed webhook
        event arrives for an organization that started a checkout (see
        start_checkout). Distinct from create_subscription's own
        provider_name/provider_reference kwargs, which set them at the
        moment of creation instead; this method is what
        sync_from_webhook_event actually uses, since every organization
        already has a Subscription (created at registration, on the Free
        plan) well before it ever starts a checkout."""
        previous_provider_name = subscription.provider_name
        previous_provider_reference = subscription.provider_reference
        subscription.provider_name = provider_name
        subscription.provider_reference = provider_reference
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.provider_linked,
            actor=actor,
            previous_values={
                "provider_name": previous_provider_name,
                "provider_reference": previous_provider_reference,
            },
            new_values={"provider_name": provider_name, "provider_reference": provider_reference},
        )
        return self._commit(subscription)

    def sync_period_from_provider(
        self,
        subscription: Subscription,
        *,
        current_period_start: datetime,
        current_period_end: datetime,
        cancel_at_period_end: bool,
        actor: User | None = None,
    ) -> Subscription:
        """Overwrites current_period_start/end/cancel_at_period_end with
        the provider's own values -- distinct from renew(), which
        advances by this app's own fixed period length (30/365 days)
        because THAT method exists specifically for subscriptions with no
        provider driving real billing-cycle dates. Once a subscription is
        provider-attached, its dates come from here (driven by a
        subscription_updated webhook event), never from renew()."""
        previous = {
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "cancel_at_period_end": subscription.cancel_at_period_end,
        }
        subscription.current_period_start = current_period_start
        subscription.current_period_end = current_period_end
        subscription.cancel_at_period_end = cancel_at_period_end
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.provider_subscription_updated,
            actor=actor,
            previous_values=previous,
            new_values={
                "current_period_start": current_period_start.isoformat(),
                "current_period_end": current_period_end.isoformat(),
                "cancel_at_period_end": cancel_at_period_end,
            },
        )
        return self._commit(subscription)

    def mark_past_due(self, subscription: Subscription, *, actor: User | None = None) -> Subscription:
        """A provider-side renewal payment failed -- moves the
        subscription to `past_due`. A no-op if already past_due, same
        "callers never have to check status first" convention as
        activate_subscription. Recovering from past_due happens via
        activate_subscription (payment eventually succeeds) or
        cancel_immediately (the provider gives up retrying), driven by
        whatever subsequent webhook event the provider sends -- this
        method only records the failure."""
        if subscription.status == SubscriptionStatus.past_due.value:
            return subscription
        previous_status = subscription.status
        subscription.status = SubscriptionStatus.past_due.value
        self._record_event(
            subscription,
            event_type=SubscriptionEventType.payment_failed,
            actor=actor,
            previous_values={"status": previous_status},
            new_values={"status": subscription.status},
        )
        return self._commit(subscription)

    def start_checkout(
        self,
        subscription: Subscription,
        plan: Plan,
        billing_period: BillingPeriod,
        *,
        actor: User,
        success_url: str,
        cancel_url: str,
    ) -> ProviderCheckoutSession:
        """Starts a hosted checkout session for moving `subscription`'s
        organization onto `plan`/`billing_period`. Never mutates
        `subscription` itself -- see BillingProvider
        .create_checkout_session's own docstring on why that only
        happens once a checkout_completed webhook event actually arrives
        (payment can fail, be abandoned, or need a 3-D-Secure round trip
        entirely on the provider's own hosted page).

        Reuses the organization's cached provider customer (see
        _get_or_create_provider_customer) instead of creating a fresh one
        on every call -- Phase 18.1 hardening; Phase 18 originally created
        one on every checkout, documented then as a scope trade-off this
        method now resolves."""
        customer_reference = self._get_or_create_provider_customer(
            subscription.organization_id, actor_email=actor.email
        )
        request = CheckoutSessionRequest(
            customer_reference=customer_reference,
            plan=plan,
            billing_period=billing_period,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "organization_id": subscription.organization_id,
                "plan_id": plan.id,
                "billing_period": billing_period.value,
            },
        )
        return self.provider.create_checkout_session(request)

    def start_portal_session(self, subscription: Subscription, *, return_url: str) -> ProviderPortalSession:
        """Starts a hosted billing-management session for `subscription`'s
        organization -- unlike start_checkout, this requires an EXISTING
        provider customer (app.models.ProviderCustomer); an organization
        that has never checked out has nothing to manage on the
        provider's side yet. Raises LookupError if no provider customer
        is on file for self.provider.name -- app.routers.billing maps
        that to a 404, prompting the tenant to subscribe via checkout
        first."""
        customer = self.db.scalar(
            select(ProviderCustomer).where(
                ProviderCustomer.organization_id == subscription.organization_id,
                ProviderCustomer.provider_name == self.provider.name,
            )
        )
        if customer is None:
            raise LookupError(
                f"No {self.provider.name} customer is on file for organization "
                f"{subscription.organization_id!r} -- start a checkout first."
            )
        return self.provider.create_portal_session(
            customer_reference=customer.provider_customer_id, return_url=return_url
        )

    def _get_or_create_provider_customer(self, organization_id: str, *, actor_email: str) -> str:
        """Returns the cached provider_customer_id for
        (organization_id, self.provider.name) -- app.models.ProviderCustomer
        -- creating one via self.provider.create_customer only on a cache
        miss. Concurrency-safe: two simultaneous callers can both miss the
        cache and both call provider.create_customer (producing two
        distinct, harmless provider-side customer records -- Stripe
        tolerates this fine, same as before this caching existed), but
        the UNIQUE(organization_id, provider_name) constraint means only
        ONE of the two resulting rows is ever persisted. The loser
        catches the IntegrityError, rolls back its own half-done insert,
        and re-reads the winner's row instead of raising -- so every
        caller still gets back A valid, shared provider_customer_id, even
        though up to one extra provider-side customer record may exist
        as an untracked byproduct of the race. This is the same
        catch-IntegrityError-and-defer-to-the-winner pattern
        app.routers.billing_webhooks already uses for ProviderWebhookReceipt."""
        existing = self.db.scalar(
            select(ProviderCustomer).where(
                ProviderCustomer.organization_id == organization_id,
                ProviderCustomer.provider_name == self.provider.name,
            )
        )
        if existing is not None:
            return existing.provider_customer_id

        customer = self.provider.create_customer(
            organization_id=organization_id, email=actor_email, name=actor_email
        )
        record = ProviderCustomer(
            organization_id=organization_id,
            provider_name=self.provider.name,
            provider_customer_id=customer.id,
        )
        self.db.add(record)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(ProviderCustomer).where(
                    ProviderCustomer.organization_id == organization_id,
                    ProviderCustomer.provider_name == self.provider.name,
                )
            )
            if existing is None:
                raise
            return existing.provider_customer_id
        return customer.id

    def sync_from_webhook_event(
        self, event: ProviderWebhookEvent, *, actor: User | None = None
    ) -> Subscription:
        """The single entry point every provider webhook (regardless of
        which concrete provider produced it) drives Subscription state
        through -- translates the normalized BillingProviderEventType
        vocabulary (app.billing.provider_base) into the existing
        lifecycle methods above. This is what keeps the domain layer
        provider-agnostic: this method's own logic never branches on a
        provider's own event-naming, only on BillingProviderEventType.

        Raises LookupError if no matching Subscription can be found --
        app.routers.billing_webhooks maps that to a 404/ignored response
        rather than ever silently dropping an event."""
        if event.event_type == BillingProviderEventType.checkout_completed:
            organization_id = event.metadata.get("organization_id")
            plan_id = event.metadata.get("plan_id")
            billing_period_value = event.metadata.get("billing_period")
            if not organization_id or not plan_id or not billing_period_value:
                raise ValueError(
                    "checkout_completed event is missing organization_id/plan_id/"
                    "billing_period in its metadata"
                )
            subscription = self.db.scalar(
                select(Subscription).where(Subscription.organization_id == organization_id)
            )
            if subscription is None:
                raise LookupError(f"No subscription found for organization_id={organization_id!r}")
            plan = self.db.get(Plan, plan_id)
            if plan is None:
                raise LookupError(f"Plan {plan_id!r} referenced by checkout event does not exist")

            subscription = self.attach_provider_subscription(
                subscription,
                provider_name=event.provider_name,
                provider_reference=event.provider_reference,
                actor=actor,
            )
            subscription = self.change_plan(subscription, plan, actor=actor)
            if subscription.billing_period != billing_period_value:
                subscription = self.change_billing_period(
                    subscription, BillingPeriod(billing_period_value), actor=actor
                )
            subscription = self.activate_subscription(subscription, actor=actor)
            return subscription

        subscription = self.get_subscription_by_provider_reference(
            provider_name=event.provider_name, provider_reference=event.provider_reference
        )
        if subscription is None:
            raise LookupError(
                f"No subscription attached to provider_name={event.provider_name!r} "
                f"provider_reference={event.provider_reference!r}"
            )

        if event.event_type == BillingProviderEventType.subscription_updated:
            if event.subscription_state is None:
                raise ValueError("subscription_updated event is missing subscription_state")
            return self.sync_period_from_provider(
                subscription,
                current_period_start=event.subscription_state.current_period_start,
                current_period_end=event.subscription_state.current_period_end,
                cancel_at_period_end=event.subscription_state.cancel_at_period_end,
                actor=actor,
            )
        if event.event_type == BillingProviderEventType.subscription_canceled:
            return self.cancel_immediately(subscription, actor=actor)
        if event.event_type == BillingProviderEventType.payment_failed:
            return self.mark_past_due(subscription, actor=actor)

        raise ValueError(f"Unhandled BillingProviderEventType: {event.event_type!r}")

    # --- validation -----------------------------------------------------

    def validate_subscription(self, subscription: Subscription) -> list[str]:
        """Pure invariant checker -- no database access, no mutation.
        Returns a list of human-readable problems (empty if none). Used
        by tests and available for a future defensive check before a
        risky mutation; nothing in this class calls it automatically
        today."""
        errors: list[str] = []
        if subscription.current_period_end <= subscription.current_period_start:
            errors.append("current_period_end must be after current_period_start")
        if bool(subscription.trial_start) != bool(subscription.trial_end):
            errors.append("trial_start and trial_end must be set together")
        if (
            subscription.trial_start
            and subscription.trial_end
            and subscription.trial_end <= subscription.trial_start
        ):
            errors.append("trial_end must be after trial_start")
        if subscription.status == SubscriptionStatus.canceled.value and subscription.canceled_at is None:
            errors.append("a canceled subscription must have canceled_at set")
        return errors
