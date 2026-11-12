#!/usr/bin/env node
/** Build, render and validate an image-first PPTX in a Codex Artifact Tool runtime. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--help') return {help: true};
    if (!argv[i].startsWith('--') || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error('Expected --key value');
    args[argv[i].slice(2)] = argv[++i];
  }
  return args;
}
function rectangle(p, canvas) {
  if (!p || !['left', 'top', 'width', 'height'].every(k => Number.isFinite(p[k]))) throw new Error('Invalid position');
  if (p.left < 0 || p.top < 0 || p.width <= 0 || p.height <= 0 || p.left + p.width > canvas.width + 0.01 || p.top + p.height > canvas.height + 0.01) throw new Error('Position outside slide');
  return p;
}
async function imageBytes(file) {
  const types = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp'};
  const contentType = types[path.extname(file).toLowerCase()];
  if (!contentType) throw new Error('Expected a PNG/JPEG/WebP input: ' + file);
  const bytes = await fs.readFile(file);
  return {blob: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), contentType};
}
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('Usage: node build_image_deck.mjs --manifest FILE --out FILE.pptx --runtime-modules DIR --presentation-skill-dir DIR --python EXE [--build-dir DIR]');
    return;
  }
  for (const key of ['manifest','out','runtime-modules','presentation-skill-dir','python']) if (!args[key]) throw new Error('Missing --' + key);
  const manifestPath = path.resolve(args.manifest);
  const base = path.dirname(manifestPath);
  const finalPath = path.resolve(args.out);
  if (path.extname(finalPath).toLowerCase() !== '.pptx') throw new Error('--out must end in .pptx');
  try { await fs.access(finalPath); throw new Error('Output exists; choose a new filename'); }
  catch (e) { if (e.code !== 'ENOENT') throw e; }
  const buildDir = path.resolve(args['build-dir'] || path.join(path.dirname(finalPath), '.build'));
  if (buildDir === path.dirname(finalPath)) throw new Error('Use a separate private build directory');
  const skillDir = path.resolve(args['presentation-skill-dir']);
  const runtimeModules = path.resolve(args['runtime-modules']);
  const spec = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  const canvas = spec.slide_size || {width:1600, height:900};
  if (!Number.isFinite(canvas.width) || !Number.isFinite(canvas.height) || canvas.width <= 0 || canvas.height <= 0) throw new Error('Invalid slide_size');
  if (!Array.isArray(spec.slides) || !spec.slides.length) throw new Error('No slides in manifest');
  const ids = new Set(), fonts = new Set();
  for (const slide of spec.slides) {
    if (!slide.id || ids.has(slide.id)) throw new Error('Missing or duplicate slide ID');
    ids.add(slide.id);
    if (!slide.image) throw new Error('Missing slide image');
    await fs.access(path.resolve(base, slide.image));
    for (const figure of slide.figures || []) {
      rectangle(figure.position, canvas);
      await fs.access(path.resolve(base, figure.image));
    }
    for (const text of slide.editable_text || []) {
      rectangle(text.position, canvas);
      if (!text.font_family || !Number.isFinite(text.font_size) || text.font_size <= 0) throw new Error('Editable text requires verified font_family and positive font_size');
      fonts.add(text.font_family);
    }
    for (const cite of slide.citations || []) if (cite.doi && !/^10\.\d{4,9}\/\S+$/.test(cite.doi)) throw new Error('Invalid DOI string; use verified metadata');
  }
  const marker = path.join(skillDir, 'container_tools/mark_artifact_operation_started.mjs');
  const utils = path.join(skillDir, 'container_tools/artifact_tool_utils.mjs');
  await fs.access(marker); await fs.access(utils);
  const require = createRequire(import.meta.url);
  const artifactEntry = require.resolve('@oai/artifact-tool', {paths:[runtimeModules]});
  const {Presentation, PresentationFile} = await import(pathToFileURL(artifactEntry).href);
  process.env.RUNTIME_NODE_MODULES = runtimeModules;
  const marked = spawnSync(process.execPath, [marker,'--operation-kind','create','--expected-output-count','1','--output-format','pptx'], {cwd:skillDir,encoding:'utf8'});
  if (marked.status !== 0) throw new Error('Operation marker failed: ' + (marked.stderr || marked.stdout));
  await fs.mkdir(buildDir, {recursive:true});
  await fs.mkdir(path.dirname(finalPath), {recursive:true});
  const presentation = Presentation.create({slideSize:canvas});
  for (const [i, item] of spec.slides.entries()) {
    const slide = presentation.slides.add();
    slide.background.fill = '#FFFFFF';
    slide.images.add({...await imageBytes(path.resolve(base,item.image)), alt:item.title || String(item.id), fit:'contain', position:{left:0,top:0,...canvas}});
    for (const figure of item.figures || []) slide.images.add({...await imageBytes(path.resolve(base,figure.image)), alt:figure.alt || '', fit:'contain', position:figure.position});
    for (const [j, text] of (item.editable_text || []).entries()) {
      const box = slide.shapes.add({geometry:'textbox',name:`editable-${i+1}-${j+1}`,position:text.position,fill:'none',line:{fill:'none',width:0}});
      box.text = text.text || '';
      box.text.style = {typeface:text.font_family,fontSize:text.font_size,color:text.color || '#153957'};
    }
    const citations = (item.citations || []).map(c => [c.id,c.title,c.doi ? 'https://doi.org/' + c.doi : c.url,c.locator].filter(Boolean).join(' | '));
    if (spec.include_notes === true) {
      slide.speakerNotes.text = [item.notes || '',citations.length ? '\nSources:\n' + citations.join('\n') : ''].join('\n');
    }
    const preview = await presentation.export({slide,format:'png',scale:1});
    await fs.writeFile(path.join(buildDir,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await preview.arrayBuffer()));
  }
  const candidatePath = path.join(buildDir,'candidate.pptx');
  await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
  const {finalizePresentation} = await import(pathToFileURL(utils).href);
  const fontPolicy = fonts.size ? {basis:'design',families:[...fonts]} : undefined;
  const result = await finalizePresentation({workspaceDir:path.dirname(buildDir),candidatePath,finalPath,
    pythonExecutable:path.resolve(args.python),explicitTotalSlideCount:spec.slides.length,
    requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],fontPolicy,
    integrityValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),
    layoutArgs:['--expected-slide-size-emu',`${Math.round(canvas.width*9525)},${Math.round(canvas.height*9525)}`],
    verifyArtifactToolImport:true,receiptPath:path.join(buildDir,'validation.json')});
  console.log(JSON.stringify({finalPath:result.finalPath,slides:spec.slides.length,previews:buildDir}));
}
main().catch(e => {console.error(e.stack || String(e)); process.exitCode=1;});
