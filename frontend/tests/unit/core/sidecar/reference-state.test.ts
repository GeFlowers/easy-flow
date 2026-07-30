import { expect, test } from "@rstest/core";

import {
  getNextSidecarOpenState,
  type SidecarReferenceStateItem,
} from "@/core/sidecar/reference-state";

const firstReference: SidecarReferenceStateItem = {
  id: 1,
  context: {
    type: "referenced_message",
    label: "Selected assistant text #1",
    messageId: "msg-1",
    role: "assistant",
    content: "First selected text.",
  },
};

const secondReference: SidecarReferenceStateItem = {
  id: 2,
  context: {
    type: "referenced_message",
    label: "Selected assistant text #1",
    messageId: "msg-1",
    role: "assistant",
    content: "Second selected text.",
  },
};

/**
 * 覆盖“keeps the existing sidecar thread when adding a new reference”这一可观察行为，防止相关边界在重构后回归。

 */

test("keeps the existing sidecar thread when adding a new reference", () => {
  const nextState = getNextSidecarOpenState({
    open: true,
    sidecarThreadId: "sidecar-thread-1",
    activeReferences: [],
    nextReference: secondReference,
  });

  expect(nextState.sidecarThreadId).toBe("sidecar-thread-1");
  expect(nextState.activeReferences).toEqual([secondReference]);
});

/**
 * 覆盖“accumulates references while drafting a new sidecar thread”这一可观察行为，防止相关边界在重构后回归。

 */

test("accumulates references while drafting a new sidecar thread", () => {
  const nextState = getNextSidecarOpenState({
    open: true,
    sidecarThreadId: null,
    activeReferences: [firstReference],
    nextReference: secondReference,
  });

  expect(nextState.sidecarThreadId).toBeNull();
  expect(nextState.activeReferences).toEqual([firstReference, secondReference]);
});
