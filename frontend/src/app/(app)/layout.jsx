"use client";

import { CreateIssueDialog } from "@/components/issue/create-issue-dialog";
import { AppProvider } from "@/components/shell/app-context";
import { TopNav } from "@/components/shell/top-nav";
import { PageSpinner } from "@/components/ui/button";
import { useMe } from "@/lib/api/hooks";
import { RealtimeProvider } from "@/lib/realtime";

export default function AppLayout({ children }) {
  const me = useMe();
  if (me.isPending) return <div className="h-screen"><PageSpinner /></div>;
  if (!me.data) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 text-center">
        <p className="text-fg-subtle">No se pudo cargar tu sesión.</p>
        <a className="text-link hover:underline" href="/auth/login">Iniciar sesión</a>
      </div>
    );
  }
  return (
    <AppProvider me={me.data}>
      <RealtimeProvider userId={me.data.id}>
        <div className="flex h-screen flex-col">
          <TopNav />
          <div className="flex min-h-0 flex-1">{children}</div>
        </div>
        <CreateIssueDialog />
      </RealtimeProvider>
    </AppProvider>
  );
}
