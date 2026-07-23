import type { ReactNode } from "react";

import { PlatformAdminShell } from "@/components/layout/PlatformAdminShell";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <PlatformAdminShell>{children}</PlatformAdminShell>;
}
