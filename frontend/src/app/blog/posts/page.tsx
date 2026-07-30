import { PostList } from "@/components/landing/post-list";
import { getAllPosts, getPreferredBlogLang } from "@/core/blog";
import { getI18n } from "@/core/i18n/server";

import { useMDXComponents as getMDXComponents } from "../../../mdx-components";

// Nextra 以未绑定方法暴露包装组件；此处仅保存组件引用。
// eslint-disable-next-line @typescript-eslint/unbound-method
const Wrapper = getMDXComponents().wrapper;

/** 定义全部博客文章列表页的 MDX 元数据。 */
export const metadata = {
  title: "All Posts",
  filePath: "blog/index.mdx",
};

/** 根据用户语言偏好加载并渲染全部博客文章。 */
export default async function PostsPage() {
  const { locale } = await getI18n();
  const posts = await getAllPosts(getPreferredBlogLang(locale));

  return (
    <Wrapper toc={[]} metadata={metadata} sourceCode="">
      <PostList title={metadata.title} posts={posts} />
    </Wrapper>
  );
}
