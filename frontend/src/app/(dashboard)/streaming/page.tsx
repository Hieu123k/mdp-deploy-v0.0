"use client";

import { PageHeader } from "@/components/layout/PageHeader";
import { StreamingEditor } from "@/components/streaming/StreamingEditor";

export default function StreamingPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Streaming"
        subtitle="Watermark-incremental sync (Oracle change → upsert into Postgres). Enable a table to auto-migrate."
      />
      <StreamingEditor />
    </div>
  );
}
