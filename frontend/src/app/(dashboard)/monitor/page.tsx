"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Monitor page redirects to the dashboard. */
export default function MonitorRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/");
  }, [router]);
  return null;
}
