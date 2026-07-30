import { Cards as NextraCards } from "nextra/components";
import type { ComponentProps } from "react";

import { LocalizedCard } from "./localized-mdx-components";

/** LocalizedCardsRoot 内部组件：组织对应的界面结构与交互语义。 */
function LocalizedCardsRoot(props: ComponentProps<typeof NextraCards>) {
  return <NextraCards {...props} />;
}

/** LocalizedCards 组件：提供对应的界面结构与交互语义。 */
export const LocalizedCards = Object.assign(LocalizedCardsRoot, {
  Card: LocalizedCard,
  displayName: "LocalizedCards",
});
