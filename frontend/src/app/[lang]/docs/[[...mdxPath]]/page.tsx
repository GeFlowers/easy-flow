import { generateStaticParamsFor, importPage } from "nextra/pages";

import { useMDXComponents as getMDXComponents } from "../../../../mdx-components";

/** 为可静态生成的文档路径提供路由参数。 */
export const generateStaticParams = generateStaticParamsFor("mdxPath");

/** 从当前语言的 MDX 文档导出页面元数据。 */
export async function generateMetadata(props) {
  const params = await props.params;
  const { metadata } = await importPage(params.mdxPath, params.lang);
  return metadata;
}

// Nextra 以未绑定方法暴露包装组件；此处仅提取引用，不会调用其 this 上下文。
// eslint-disable-next-line @typescript-eslint/unbound-method
const Wrapper = getMDXComponents().wrapper;

/** 加载并渲染匹配路径与语言的 MDX 文档页面。 */
export default async function Page(props) {
  const params = await props.params;
  const {
    default: MDXContent,
    toc,
    metadata,
    sourceCode,
  } = await importPage(params.mdxPath, params.lang);
  return (
    <Wrapper toc={toc} metadata={metadata} sourceCode={sourceCode}>
      <MDXContent {...props} params={params} />
    </Wrapper>
  );
}
