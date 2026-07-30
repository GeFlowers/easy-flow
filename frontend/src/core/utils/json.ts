import { parse } from "best-effort-json-parser";

/** 尝试解析数据字符串，解析失败时返回未定义值。 */
export function tryParseJSON(json: string) {
  try {
    const object = parse(json);
    return object;
  } catch {
    return undefined;
  }
}
