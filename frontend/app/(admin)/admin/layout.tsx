import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PlatformAdminShell } from "@/components/layout/PlatformAdminShell";

// Distinguishes the browser tab from the tenant app's own "Invoicing"
// title -- part of keeping the two contexts visually unambiguous.
export const metadata: Metadata = {
  title: "Platform Admin | Invoicing",
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <PlatformAdminShell>{children}</PlatformAdminShell>;
}
