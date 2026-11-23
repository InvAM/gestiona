"use client";

import { notFound } from "next/navigation";
import { use } from "react";
import { ADMIN_SECTIONS, AdminSettings } from "@/components/settings/admin";

export default function AdminSectionPage({ params }) {
  const { section } = use(params);
  if (!ADMIN_SECTIONS.some(([v]) => v === section)) notFound();
  return <AdminSettings section={section} />;
}
