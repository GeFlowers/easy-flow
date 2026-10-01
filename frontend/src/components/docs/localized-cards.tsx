import { Cards as NextraCards } from "nextra/components";
import type { ComponentProps } from "react";

import { LocalizedCard } from "./localized-mdx-components";

/** 保留 Nextra 卡片组的默认布局，并转发调用方传入的属性和子卡片。 */
function LocalizedCardsRoot(props: ComponentProps<typeof NextraCards>) {
  return <NextraCards {...props} />;
}

/** 暴露卡片组及经过本地化处理的 Card 子组件供 MDX 使用。 */
export const LocalizedCards = Object.assign(LocalizedCardsRoot, {
  Card: LocalizedCard,
  displayName: "LocalizedCards",
});
