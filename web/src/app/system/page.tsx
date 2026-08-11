"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SystemPage() {
  const router = useRouter();
  useEffect(() => { router.replace("/system/diagnose"); }, [router]);
  return null;
}