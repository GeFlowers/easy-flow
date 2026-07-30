import { expect, test } from "@rstest/core";

import {
  buildReferenceMessageMetadata,
  readReferenceMessageContexts,
  type SidecarContext,
} from "@/core/sidecar";

const contexts: SidecarContext[] = [
  {
    type: "referenced_message",
    label: "Selected assistant text #2",
    messageId: "parent-ai-1",
    role: "assistant",
    content: "Build it as a side conversation.",
  },
  {
    type: "referenced_message",
    label: "Selected assistant text #2",
    messageId: "parent-ai-1",
    role: "assistant",
    content: "Keep the cited snippets compact.",
  },
];

/**
 * 覆盖“builds visible message reference metadata for selected contexts”这一可观察行为，防止相关边界在重构后回归。

 */

test("builds visible message reference metadata for selected contexts", () => {
  expect(buildReferenceMessageMetadata(contexts)).toEqual({
    referenced_message_count: 2,
    referenced_message_ids: ["parent-ai-1", "parent-ai-1"],
    referenced_message_roles: ["assistant", "assistant"],
    referenced_message_contexts: [
      {
        label: "Selected assistant text #2",
        message_id: "parent-ai-1",
        role: "assistant",
        content: "Build it as a side conversation.",
      },
      {
        label: "Selected assistant text #2",
        message_id: "parent-ai-1",
        role: "assistant",
        content: "Keep the cited snippets compact.",
      },
    ],
  });
});

/**
 * 覆盖“reads visible message reference metadata defensively”这一可观察行为，防止相关边界在重构后回归。

 */

test("reads visible message reference metadata defensively", () => {
  expect(
    readReferenceMessageContexts({
      referenced_message_contexts: [
        {
          label: "Selected assistant text #2",
          message_id: "parent-ai-1",
          role: "assistant",
          content: "Build it as a side conversation.",
        },
        {
          label: 42,
          message_id: "ignored",
          role: "assistant",
          content: "Bad reference",
        },
      ],
    }),
  ).toEqual([
    {
      type: "referenced_message",
      label: "Selected assistant text #2",
      messageId: "parent-ai-1",
      role: "assistant",
      content: "Build it as a side conversation.",
    },
  ]);
});
