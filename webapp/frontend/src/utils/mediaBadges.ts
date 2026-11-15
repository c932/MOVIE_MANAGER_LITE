import manifest from '../../../../logo/media-badges/manifest.json';

export function technologyBadges(resolution = '', hdrType = '') {
  const result: {key: string; title: string; file?: string}[] = [];
  const value = resolution.toLowerCase().replace(/[\s_-]/g, '');
  if (resolution) {
    const entry = Object.entries(manifest.resolution).find(([, info]) => info.aliases.includes(value));
    result.push(entry ? {key: entry[0], title: resolution, file: entry[1].file} : {key: 'resolution', title: resolution});
  }
  const compact = hdrType.toLowerCase().replace(/[\s._-]/g, '');
  const dv = compact.includes('dolbyvision') || compact.includes('dovi') || /\bdv\b/i.test(hdrType);
  const hdr = compact.includes('hdr') || compact.includes('hlg');
  if (hdr) result.push({key: 'hdr', title: hdrType, file: manifest.hdr.file});
  if (dv) result.push({key: 'dolbyvision', title: hdrType, file: manifest.dolbyvision.file});
  if (hdrType && !dv && !hdr) result.push({key: 'dynamic-range', title: hdrType});
  return result;
}

