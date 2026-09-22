import type { RequirementSourceDraft } from "./requirement-editor-cache";

type Preview = (workspace: string, content: string) => Promise<{ title: string; content: string; warnings: string[] }>;
interface PreviewServices {
  previewRequirementEmail: Preview;
  previewRequirementDocx: Preview;
  previewRequirementPdf: Preview;
}

/** Prepare a complete replacement before the caller changes any existing draft. */
export async function prepareRequirementSource(
  file: Pick<File, "name" | "size" | "arrayBuffer">,
  workspace: string,
  previews: PreviewServices,
): Promise<RequirementSourceDraft> {
  if (!/\.(txt|md|eml|docx|pdf|vtt|srt)$/i.test(file.name)) throw new Error("Choose a TXT, Markdown, EML, DOCX, PDF, VTT or SRT file. Text files must use UTF-8.");
  if (file.size > 400000) throw new Error("Choose a file smaller than 400 KB.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (/\.(eml|docx|pdf)$/i.test(file.name)) {
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    const email = /\.eml$/i.test(file.name);
    const preview = email ? previews.previewRequirementEmail : /\.pdf$/i.test(file.name) ? previews.previewRequirementPdf : previews.previewRequirementDocx;
    const result = await preview(workspace, btoa(binary));
    return { title: result.title || file.name, kind: email ? "email" : "document", content: result.content, warnings: result.warnings };
  }
  let content: string;
  try { content = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new Error("This text file is not valid UTF-8. Export it as UTF-8 and import it again."); }
  if (content.length > 100000 || content.includes("\0")) throw new Error("Source text must contain at most 100,000 characters and no NUL characters.");
  if (content.trim().length < 10) throw new Error("The file needs at least 10 characters of source text.");
  return { title: file.name, kind: /\.(vtt|srt)$/i.test(file.name) ? "transcript" : "document", content, warnings: [] };
}
