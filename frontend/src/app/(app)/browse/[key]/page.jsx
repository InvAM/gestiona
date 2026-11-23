"use client";

import { useRouter } from "next/navigation";
import { use, useEffect } from "react";
import { IssueView } from "@/components/issue/issue-view";
import { useIssue } from "@/lib/api/hooks";
import { ProjectSidebar } from "@/components/shell/project-sidebar";

export default function BrowseIssuePage({ params }) {
  const { key } = use(params);
  const issueKey = decodeURIComponent(key).toUpperCase();
  const issue = useIssue(issueKey);
  const router = useRouter();
  useEffect(() => {
    if (!issue.data) return;
    document.title = `[${issue.data.key}] ${issue.data.summary} · Gestiona`;
    // old key of a moved issue → canonical URL
    if (issue.data.key !== issueKey) router.replace(`/browse/${issue.data.key}`);
  }, [issue.data, issueKey, router]);
  return (
    <>
      {issue.data && <ProjectSidebar projectKey={issue.data.project.key} />}
      <main className="flex min-w-0 flex-1 flex-col"><IssueView issueKey={issueKey} /></main>
    </>
  );
}
