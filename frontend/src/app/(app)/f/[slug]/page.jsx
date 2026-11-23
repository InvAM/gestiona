"use client";

import { use } from "react";
import { PublicForm } from "@/components/forms/forms";

export default function PublicFormPage({ params }) {
  const { slug } = use(params);
  return <main className="flex min-w-0 flex-1 flex-col overflow-auto px-4"><PublicForm slug={slug} /></main>;
}
