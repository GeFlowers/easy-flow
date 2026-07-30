import type { Folder, MdxFile, PageMapItem } from "nextra";
import { getPageMap } from "nextra/page-map";
import { cache } from "react";

import { getLangByLocale, type Locale } from "@/core/i18n/locale";

/** 博客内容树当前支持的语言代码。 */
export const BLOG_LANGS = ["zh", "en"] as const;
const RECENT_POST_LIMIT = 5;

/** 博客内容树支持的语言代码联合类型。 */
export type BlogLang = (typeof BLOG_LANGS)[number];

/** 博客文章在页面映射中使用的元数据。 */
export type BlogMetadata = {
  date?: string;
  description?: string;
  item: MdxFile;
  tags: string[];
  title: string;
};

type BlogMdxFile = MdxFile & {
  frontMatter?: {
    date?: string;
    description?: string;
    tags?: unknown;
    title?: string;
  };
  title?: string;
};

/** 合并语言变体后对外提供的博客文章。 */
export type BlogPost = {
  lang: BlogLang;
  languages: BlogLang[];
  metadata: BlogMetadata;
  slug: string[];
  title: string;
};

type LocalizedBlogPost = {
  lang: BlogLang;
  metadata: BlogMetadata;
  slug: string[];
  title: string;
};

/** 渲染博客索引页所需的页面映射、文章和标签集合。 */
export type BlogIndexData = {
  pageMap: PageMapItem[];
  posts: BlogPost[];
  recentPosts: BlogPost[];
  tags: Array<{ name: string; count: number; posts: BlogPost[] }>;
};

/** 判断页面映射项是否为包含子项的文件夹。 */
function isFolder(item: PageMapItem): item is Folder {
  return "children" in item && Array.isArray(item.children);
}

/** 判断页面映射项是否为博客 MDX 文件。 */
function isMdxFile(item: PageMapItem): item is BlogMdxFile {
  return "name" in item && "route" in item && !isFolder(item);
}

/** 将语言目录中的博客路由归一为对外公开的 `/blog` 路由。 */
function normalizeBlogRoute(route: string): string {
  // 文章来自按语言划分的内容树，但统一暴露在公开的 /blog 路由下。
  return route.replace(/^\/(en|zh)\/(?:posts|blog)(?=\/|$)/, "/blog");
}

/** 根据文章 slug 生成公开博客路由。 */
export function getBlogRoute(slug: string[]): string {
  return slug.length === 0 ? "/blog" : `/blog/${slug.join("/")}`;
}

/** 从公开博客路由提取文章 slug 片段。 */
function getSlugFromRoute(route: string): string[] {
  return route
    .replace(/^\/blog\/?/, "")
    .split("/")
    .filter(Boolean);
}

/** 将 slug 片段拼成用于分组和索引的稳定键。 */
function getSlugKey(slug: string[]): string {
  return slug.join("/");
}

/** 从文章前置元数据中筛出有效的字符串标签。 */
function parseTags(tags: unknown): string[] {
  if (!Array.isArray(tags)) {
    return [];
  }

  return tags.filter(
    (tag): tag is string => typeof tag === "string" && tag.length > 0,
  );
}

/** 将可选日期转换为排序时间戳；无效值按最早时间处理。 */
function parseDate(value: string | undefined): number {
  if (!value) {
    return 0;
  }

  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

/** 在可用语言中优先选择请求语言，否则按固定回退顺序选择。 */
function selectPreferredLanguage(
  languages: BlogLang[],
  preferredLang?: BlogLang,
): BlogLang | null {
  if (preferredLang && languages.includes(preferredLang)) {
    return preferredLang;
  }

  // 固定回退顺序，确保首选语言缺失时合并文章仍能稳定解析。
  for (const lang of BLOG_LANGS) {
    if (languages.includes(lang)) {
      return lang;
    }
  }

  return null;
}

/** 递归收集指定语言内容树中的博客文章元数据。 */
function collectLocalizedBlogPosts(
  items: PageMapItem[],
  lang: BlogLang,
): LocalizedBlogPost[] {
  const posts: LocalizedBlogPost[] = [];

  for (const item of items) {
    if (isFolder(item)) {
      posts.push(...collectLocalizedBlogPosts(item.children, lang));
      continue;
    }

    if (!isMdxFile(item)) {
      continue;
    }

    const route = normalizeBlogRoute(item.route);
    const slug = getSlugFromRoute(route);

    if (slug.length === 0) {
      continue;
    }

    const title = item.frontMatter?.title ?? item.title ?? item.name;

    posts.push({
      lang,
      metadata: {
        date: item.frontMatter?.date,
        description:
          typeof item.frontMatter?.description === "string"
            ? item.frontMatter.description
            : undefined,
        item: {
          ...item,
          route,
        },
        tags: parseTags(item.frontMatter?.tags),
        title,
      },
      slug,
      title,
    });
  }

  return posts;
}

/** 按 slug 合并多语言文章，并保留所有语言和标签信息。 */
function mergePostsBySlug(
  posts: LocalizedBlogPost[],
  preferredLang?: BlogLang,
): BlogPost[] {
  const postsBySlug = new Map<string, LocalizedBlogPost[]>();

  for (const post of posts) {
    const key = getSlugKey(post.slug);
    const group = postsBySlug.get(key) ?? [];
    group.push(post);
    postsBySlug.set(key, group);
  }

  return [...postsBySlug.values()]
    .flatMap((group): BlogPost[] => {
      const languages = group.map((post) => post.lang);
      const selectedLang = selectPreferredLanguage(languages, preferredLang);
      const primary =
        group.find((post) => post.lang === selectedLang) ?? group[0];

      if (!primary) {
        return [];
      }

      const mergedTags = new Set<string>();
      for (const post of group) {
        for (const tag of post.metadata.tags) {
          mergedTags.add(tag);
        }
      }

      return [
        {
          ...primary,
          languages,
          metadata: {
            ...primary.metadata,
            tags: [...mergedTags],
          },
        },
      ];
    })
    .sort((a, b) => parseDate(b.metadata.date) - parseDate(a.metadata.date));
}

/** 创建供 Nextra 页面映射使用的文件夹节点。 */
function createFolder(
  name: string,
  route: string,
  title: string,
  children: PageMapItem[],
): Folder {
  return {
    children,
    name,
    route,
    title,
  } as Folder;
}

/** 将博客文章转换为页面映射中的 MDX 节点。 */
function createPostItem(post: BlogPost): MdxFile {
  return {
    ...post.metadata.item,
    name: post.title,
    route: getBlogRoute(post.slug),
  };
}

/** 将标签转换为适合 URL 的小写 slug。 */
export function normalizeTagSlug(tag: string): string {
  return tag.toLowerCase().replace(/\s+/g, "-");
}

/** 将连字符分隔的标签 slug 格式化为标题式显示文本。 */
export function formatTagName(tag: string): string {
  return tag
    .split("-")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

/** 将界面区域设置映射为受支持的博客语言。 */
export function getPreferredBlogLang(locale: Locale): BlogLang | undefined {
  const lang = getLangByLocale(locale);
  return BLOG_LANGS.find((value) => value === lang);
}

/** 判断文章标签中是否包含指定的规范化标签 slug。 */
function matchTags(tags: string[], slug: string): boolean {
  for (const tag of tags) {
    if (normalizeTagSlug(tag) === slug) {
      return true;
    }
  }
  return false;
}

/** 获取并按首选语言合并所有语言内容树中的博客文章。 */
export const getAllPosts = cache(async function getAllPosts(
  preferredLang?: BlogLang,
): Promise<BlogPost[]> {
  const localizedPageMaps = await Promise.all(
    BLOG_LANGS.map(async (lang) => ({
      items: await getPageMap(`/${lang}/posts`),
      lang,
    })),
  );

  const localizedPosts = localizedPageMaps.flatMap(({ items, lang }) =>
    collectLocalizedBlogPosts(items, lang),
  );

  return mergePostsBySlug(localizedPosts, preferredLang);
});

/** 生成博客索引所需的文章、近期文章、标签和页面映射数据。 */
export async function getBlogIndexData(
  preferredLang?: BlogLang,
  filters?: {
    tag?: string;
  },
): Promise<BlogIndexData> {
  const posts = await getAllPosts(preferredLang);
  const tagFilter = filters?.tag;
  const filteredPosts = tagFilter
    ? posts.filter((post) => matchTags(post.metadata.tags, tagFilter))
    : posts;
  const recentPosts = posts.slice(0, RECENT_POST_LIMIT);
  const postsByTag = new Map<string, BlogPost[]>();

  for (const post of posts) {
    for (const tag of post.metadata.tags) {
      const group = postsByTag.get(tag) ?? [];
      group.push(post);
      postsByTag.set(tag, group);
    }
  }

  const tags = [...postsByTag.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, tagPosts]) => ({
      count: tagPosts.length,
      name,
      posts: [...tagPosts].sort(
        (a, b) => parseDate(b.metadata.date) - parseDate(a.metadata.date),
      ),
    }));

  const pageMap: PageMapItem[] = [
    {
      data: {
        posts: { title: "All Posts", type: "Page" },
        recent_posts: { title: "Recent Posts" },
        tags: { title: "Tags" },
      },
    },
    {
      name: "All Posts",
      route: "/blog/posts",
      title: "All Posts",
      frontMatter: {
        title: "All Posts",
        filePath: "blog/index.mdx",
      },
    } as MdxFile,
    createFolder(
      "recent_posts",
      "/blog/recent-posts",
      "Recent Posts",
      recentPosts.map(createPostItem),
    ),
  ];

  if (tags.length > 0) {
    pageMap.push(
      createFolder(
        "tags",
        "/blog/tags",
        "Tags",
        tags.map((tag) => {
          return {
            name: tag.name,
            title: `${tag.name} (${tag.count})`,
            route: `/blog/tags/${normalizeTagSlug(tag.name)}`,
          };
        }),
      ),
    );
  }

  return {
    pageMap,
    posts: filteredPosts,
    recentPosts,
    tags,
  };
}
