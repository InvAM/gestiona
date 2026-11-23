import { Suspense } from "react";
import { AnalyticsPage } from "@/components/analytics/analytics-page";
import { PageSpinner } from "@/components/ui/button";

export const metadata = { title: "Analíticas · Gestiona" };

export default function Page() {
  return (
    <main className="flex min-w-0 flex-1 flex-col overflow-auto">
      <Suspense fallback={<PageSpinner />}><AnalyticsPage /></Suspense>
    </main>
  );
}
