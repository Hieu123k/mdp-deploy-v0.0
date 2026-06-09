import { Sidebar } from "@/components/layout/Sidebar";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { PreferencesProvider } from "@/components/settings/PreferencesProvider";
import { NavGuard } from "@/components/settings/NavGuard";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <PreferencesProvider>
        <div className="flex">
          <Sidebar />
          <main className="h-screen flex-1 overflow-y-auto p-6">
            <NavGuard>{children}</NavGuard>
          </main>
        </div>
      </PreferencesProvider>
    </RequireAuth>
  );
}
