/** 把 Markdown 导入声明为构建期解析后的纯文本内容。 */
declare module "*.md" {
  const content: string;
  export default content;
}
