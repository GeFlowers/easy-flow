"use client";

import { SafeStreamdown } from "@/core/streamdown/components";

import { aboutMarkdown } from "./about-content";

/** 渲染关于页面，使用既有静态内容而不在组件中重写文案。 */
export function AboutSettingsPage() {
  return <SafeStreamdown>{aboutMarkdown}</SafeStreamdown>;
}
