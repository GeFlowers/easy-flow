import { notFound } from "next/navigation";

import { PostList } from "@/components/landing/post-list";
import {
  formatTagName,
  getBlogIndexData,
  getPreferredBlogLang,
} from "@/core/blog";
import { getI18n } from "@/core/i18n/server";

import { useMDXComponents as getMDXComponents } from "../../../../mdx-components";

// Nextra 以未绑定方法暴露包装组件；此处仅保存组件引用。
// eslint-disable-next-line @typescript-eslint/unbound-method
const Wrapper = getMDXComponents().wrapper;

/** 为指定博客标签生成页面元数据。 */
export async function generateMetadata(props) {
  const params = await props.params;
  return {
    title: formatTagName(params.tag),
    filePath: "blog/index.mdx",
  };
}

/** 加载并渲染当前语言下指定标签的文章列表。 */
export default async function TagPage(props) {
  const params = await props.params;
  const tag = params.tag;
  const { locale } = await getI18n();
  const { posts } = await getBlogIndexData(getPreferredBlogLang(locale), {
    tag,
  });

  if (posts.length === 0) {
    notFound();
  }

  const title = formatTagName(tag);

  return (
    <Wrapper
      toc={[]}
      metadata={{ title, filePath: "blog/index.mdx" }}
      sourceCode=""
    >
      <PostList
        title={title}
        description={`${posts.length} posts with the tag “${title}”`}
        posts={posts}
      />
    </Wrapper>
  );
}
