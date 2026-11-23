import { DashboardList } from "@/components/dashboards/dashboard-view";

export const metadata = { title: "Paneles · Gestiona" };

export default function DashboardsPage() {
  return <main className="flex min-w-0 flex-1 flex-col overflow-auto"><DashboardList /></main>;
}
