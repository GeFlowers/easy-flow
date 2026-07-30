import {
  BookOpenTextIcon,
  CompassIcon,
  FileCodeIcon,
  FileCogIcon,
  FilePlayIcon,
  FileTextIcon,
  ImageIcon,
} from "lucide-react";

const extensionMap: Record<string, string> = {
  // 文本
  txt: "text",
  csv: "csv",
  log: "text",
  conf: "text",
  config: "text",
  properties: "text",
  props: "text",

  // 脚本与类型化脚本生态
  js: "javascript",
  jsx: "jsx",
  ts: "typescript",
  tsx: "tsx",
  mjs: "javascript",
  cjs: "javascript",
  mts: "typescript",
  cts: "typescript",

  // 网页文件
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  sass: "sass",
  less: "less",
  vue: "vue",
  svelte: "svelte",
  astro: "astro",

  // 解释型语言
  py: "python",
  pyi: "python",
  pyw: "python",

  // 虚拟机语言生态
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  scala: "scala",
  groovy: "groovy",

  // 系统级语言
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cxx: "cpp",
  hpp: "cpp",
  hxx: "cpp",
  hh: "cpp",

  // 井号语言
  cs: "csharp",

  // 并发编程语言
  go: "go",

  // 系统编程语言
  rs: "rust",

  // 动态脚本语言
  rb: "ruby",
  rake: "ruby",

  // 服务器脚本语言
  php: "php",

  // 命令行脚本
  sh: "bash",
  bash: "bash",
  zsh: "zsh",
  fish: "fish",

  // 配置与数据
  json: "json",
  jsonc: "jsonc",
  json5: "json5",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  xml: "xml",
  ini: "ini",
  env: "dotenv",

  // 标记文档
  md: "markdown",
  mdx: "mdx",
  rst: "rst",

  // 结构化查询语言
  sql: "sql",

  // 其他语言
  swift: "swift",
  dart: "dart",
  lua: "lua",
  r: "r",
  matlab: "matlab",
  julia: "jl",
  elm: "elm",
  haskell: "haskell",
  hs: "haskell",
  elixir: "elixir",
  ex: "elixir",
  clj: "clojure",
  cljs: "clojure",

  // 基础设施
  dockerfile: "dockerfile",
  docker: "docker",
  tf: "terraform",
  tfvars: "terraform",
  hcl: "hcl",

  // 构建与配置
  makefile: "makefile",
  cmake: "cmake",
  gradle: "groovy",

  // 版本控制
  gitignore: "git-commit",
  gitattributes: "git-commit",

  // 其他
  graphql: "graphql",
  gql: "graphql",
  proto: "protobuf",
  prisma: "prisma",
  wasm: "wasm",
  zig: "zig",
  v: "v",
};

const browserPreviewExtensions = new Set([
  "pdf",
  "apng",
  "avif",
  "bmp",
  "gif",
  "ico",
  "jpg",
  "jpeg",
  "png",
  "webp",
  "mp3",
  "wav",
  "ogg",
  "aac",
  "m4a",
  "flac",
  "mp4",
  "mov",
  "m4v",
  "webm",
]);

/** 从路径中提取文件名。 */
export function getFileName(filepath: string) {
  return filepath.split("/").pop()!;
}

/** 从路径中提取小写文件扩展名。 */
export function getFileExtension(filepath: string) {
  return filepath.split(".").pop()!.toLocaleLowerCase();
}

/** 判断文件是否为已知代码文件，并返回语法高亮语言。 */
export function checkCodeFile(
  filepath: string,
):
  | { isCodeFile: true; language: string }
  | { isCodeFile: false; language: null } {
  const extension = getFileExtension(filepath);
  const isCodeFile = extension in extensionMap;
  if (isCodeFile) {
    return {
      isCodeFile: true,
      language: extensionMap[extension] ?? "text",
    };
  }
  return {
    isCodeFile: false,
    language: null,
  };
}

/** 判断文件扩展名是否可由浏览器直接预览。 */
export function canBrowserPreviewFile(filepath: string) {
  return browserPreviewExtensions.has(getFileExtension(filepath));
}

/** 获取适合界面展示的文件类型名称。 */
export function getFileExtensionDisplayName(filepath: string) {
  const fileName = getFileName(filepath);
  const extension = fileName.split(".").pop()!.toLocaleLowerCase();
  switch (extension) {
    case "doc":
    case "docx":
      return "Word";
    case "md":
      return "Markdown";
    case "txt":
      return "Text";
    case "ppt":
    case "pptx":
      return "PowerPoint";
    case "xls":
    case "xlsx":
      return "Excel";
    default:
      return extension.toUpperCase();
  }
}

/** 根据文件类型返回对应的图标组件。 */
export function getFileIcon(filepath: string, className?: string) {
  const extension = getFileExtension(filepath);
  const { isCodeFile } = checkCodeFile(filepath);
  switch (extension) {
    case "skill":
      return <FileCogIcon className={className} />;
    case "html":
      return <CompassIcon className={className} />;
    case "txt":
    case "md":
      return <BookOpenTextIcon className={className} />;
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "bmp":
    case "tiff":
    case "ico":
    case "webp":
    case "svg":
    case "heic":
      return <ImageIcon className={className} />;
    case "mp3":
    case "wav":
    case "ogg":
    case "aac":
    case "m4a":
    case "flac":
    case "wma":
    case "aiff":
    case "ape":
    case "mp4":
    case "mov":
    case "m4v":
      return <FilePlayIcon className={className} />;
    default:
      if (isCodeFile) {
        return <FileCodeIcon className={className} />;
      }
      return <FileTextIcon className={className} />;
  }
}
