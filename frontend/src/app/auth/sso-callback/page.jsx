"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { PageSpinner } from "@/components/ui/button";
import { safeNext } from "@/lib/auth";

function Callback() {
  const params = useSearchParams();
  useEffect(() => {
    const err = params.get("error");
    window.location.replace(err ? "/auth/login?error=sso" : safeNext(params.get("next")));
  }, [params]);
  return <PageSpinner />;
}

export default function SSOCallback() {
  return <Suspense><Callback /></Suspense>;
}
