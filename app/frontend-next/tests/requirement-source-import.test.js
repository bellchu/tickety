const assert = require('node:assert/strict');
const test = require('node:test');
const { loadPureTs } = require('./helpers/load-pure-ts');
const library = loadPureTs('requirement-source-import.ts');
const prepare = library.prepareRequirementSource;
const file = (name, bytes) => ({ name, size: bytes.length, arrayBuffer: async () => Uint8Array.from(bytes).buffer });
const textFile = (name, text) => file(name, new TextEncoder().encode(text));
const noPreview = new Proxy({}, { get() { throw new Error('Plain text must not call the server'); } });

test('text imports return a complete fresh type and warning state', async () => {
  for (const [name, kind] of [['notes.TXT', 'document'], ['notes.md', 'document'], ['meeting.vtt', 'transcript'], ['meeting.srt', 'transcript']]) {
    assert.deepEqual(await prepare(textFile(name, 'Confirm receipt within thirty seconds.'), 'workspace', noPreview), {
      title: name, kind, content: 'Confirm receipt within thirty seconds.', warnings: [],
    });
  }
});
test('invalid text is rejected before returning a replacement draft', async () => {
  for (const [input, message] of [
    [file('notes.txt', [255, 254]), /UTF-8/],
    [textFile('notes.txt', 'short'), /at least 10/],
    [textFile('notes.txt', 'Source text\0invalid'), /NUL/],
    [textFile('notes.txt', 'x'.repeat(100001)), /100,000/],
    [textFile('notes.exe', 'unaccepted file'), /Choose a TXT/],
    [{ name: 'notes.txt', size: 400001, arrayBuffer: async () => { throw new Error('must not read oversized file'); } }, /400 KB/],
  ]) await assert.rejects(prepare(input, 'workspace', noPreview), message);
});
test('document previews preserve conversion warnings and select the correct service', async () => {
  for (const [extension, service, kind] of [['eml', 'previewRequirementEmail', 'email'], ['docx', 'previewRequirementDocx', 'document'], ['pdf', 'previewRequirementPdf', 'document']]) {
    const result = await prepare(file(`source.${extension}`, [0, 128, 255]), 'workspace', {
      [service]: async (workspace, encoded) => {
        assert.equal(workspace, 'workspace');
        assert.equal(encoded, 'AID/');
        return { title: '', content: 'Confirmed extracted content', warnings: ['Images omitted'] };
      },
    });
    assert.deepEqual(result, { title: `source.${extension}`, kind, content: 'Confirmed extracted content', warnings: ['Images omitted'] });
  }
});
test('a failed preview cannot return a partial replacement', async () => {
  const error = new Error('Encrypted documents cannot be previewed');
  await assert.rejects(prepare(file('source.pdf', [1]), 'workspace', { previewRequirementPdf: async () => { throw error; } }), received => received === error);
});
