import { Sidebar } from "@/components/layout/Sidebar";
import { RequireAuth } from "@/components/auth/RequireAuth";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <div className="flex">
        <Sidebar />
        <main className="h-screen flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </RequireAuth>
  );
}
