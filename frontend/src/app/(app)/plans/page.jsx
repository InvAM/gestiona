import { PlanList } from "@/components/plans/plan-list";

export const metadata = { title: "Planes · Gestiona" };

export default function PlansPage() {
  return <main className="flex min-w-0 flex-1 flex-col overflow-auto"><PlanList /></main>;
}
