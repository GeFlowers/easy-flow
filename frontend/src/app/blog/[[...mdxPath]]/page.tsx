import { notFound } from "next/navigation";
import { importPage } from "nextra/pages";
import { cache } from "react";

import { PostList, PostMeta } from "@/components/landing/post-list";
import {
  BLOG_LANGS,
  type BlogLang,
  formatTagName,
  getAllPosts,
  getBlogIndexData,
  getPreferredBlogLang,
} from "@/core/blog";
import { getI18n } from "@/core/i18n/server";

import { useMDXComponents as getMDXComponents } from "../../../mdx-components";

// Nextra 以未绑定方法暴露包装组件；此处仅保存组件引用。
// eslint-disable-next-line @typescript-eslint/unbound-method
const Wrapper = getMDXComponents().wrapper;

/** 判断查询参数是否为受支持的博客语言代码。 */
function isBlogLang(value: string): value is BlogLang {
  return BLOG_LANGS.includes(value as BlogLang);
}

/** 缓存同一路径的多语言 MDX 查询，并按首选语言选择可用版本。 */
const loadBlogPage = cache(async function loadBlogPage(
  mdxPath: string[] | undefined,
  preferredLang?: (typeof BLOG_LANGS)[number],
) {
  const slug = mdxPath ?? [];
  const matches = await Promise.all(
    BLOG_LANGS.map(async (lang) => {
      try {
        // 查询同一公开 slug 的全部本地化源，再按当前语言选择最佳匹配。
        const page = await importPage([...slug], lang);
        return { lang, page };
      } catch {
        return null;
      }
    }),
  );

  const availableMatches = matches.filter(
    (match): match is NonNullable<(typeof matches)[number]> => match !== null,
  );

  if (availableMatches.length === 0) {
    return null;
  }

  const selected =
    (preferredLang
      ? availableMatches.find(({ lang }) => lang === preferredLang)
      : undefined) ?? availableMatches[0];

  if (!selected) {
    return null;
  }

  return {
    ...selected.page,
    lang: selected.lang,
    metadata: {
      ...selected.page.metadata,
      languages: availableMatches.map(({ lang }) => lang),
    },
    slug,
  };
});

/** 为博客首页、标签页或 MDX 文章生成对应元数据。 */
export async function generateMetadata(props) {
  const params = await props.params;
  const mdxPath = params.mdxPath ?? [];
  const { locale } = await getI18n();
  const preferredLang = getPreferredBlogLang(locale);

  if (mdxPath.length === 0) {
    return {
      title: "Blog",
    };
  }

  if (mdxPath[0] === "tags" && mdxPath[1]) {
    return {
      title: formatTagName(mdxPath[1]),
    };
  }

  const page = await loadBlogPage(mdxPath, preferredLang);

  if (!page) {
    return {};
  }

  return page.metadata;
}

/** 根据博客路径、标签及语言偏好渲染文章列表或 MDX 正文。 */
export default async function Page(props) {
  const params = await props.params;
  const searchParams = await props.searchParams;
  const mdxPath = params.mdxPath ?? [];
  const { locale } = await getI18n();
  const localePreferredLang = getPreferredBlogLang(locale);
  const queryLang = searchParams?.lang;
  const preferredLang =
    typeof queryLang === "string" && isBlogLang(queryLang)
      ? queryLang
      : localePreferredLang;

  if (mdxPath.length === 0) {
    const posts = await getAllPosts(preferredLang);
    return (
      <Wrapper
        toc={[]}
        metadata={{ title: "All Posts", filePath: "blog/index.mdx" }}
        sourceCode=""
      >
        <PostList title="All Posts" posts={posts} />
      </Wrapper>
    );
  }

  if (mdxPath[0] === "tags" && mdxPath[1]) {
    let tag: string;
    try {
      tag = decodeURIComponent(mdxPath[1]);
    } catch {
      notFound();
    }
    const title = formatTagName(tag);
    const { posts } = await getBlogIndexData(preferredLang, { tag });

    if (posts.length === 0) {
      notFound();
    }

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

  const page = await loadBlogPage(mdxPath, preferredLang);

  if (!page) {
    notFound();
  }

  const { default: MDXContent, toc, metadata, sourceCode, lang, slug } = page;
  const postMetaData = metadata as {
    date?: string;
    languages?: string[];
    tags?: unknown;
  };

  return (
    <Wrapper toc={toc} metadata={metadata} sourceCode={sourceCode}>
      <PostMeta
        currentLang={lang}
        date={
          typeof postMetaData.date === "string" ? postMetaData.date : undefined
        }
        languages={postMetaData.languages}
        pathname={slug.length === 0 ? "/blog" : `/blog/${slug.join("/")}`}
      />
      <MDXContent {...props} params={{ ...params, lang, mdxPath: slug }} />
    </Wrapper>
  );
}
