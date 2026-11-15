import {technologyBadges} from '../../utils/mediaBadges';

const assets = import.meta.glob<string>('../../../../../logo/media-badges/*.{svg,png}', {
  eager: true, query: '?url', import: 'default',
});

export function TechBadges({resolution = '', hdrType = '', compact = false}: {
  resolution?: string; hdrType?: string; compact?: boolean;
}) {
  const badges = technologyBadges(resolution, hdrType);
  if (!badges.length) return null;
  return <div className={`media-badges ${compact ? 'media-badges-compact' : ''}`} aria-label="视频格式">
    {badges.map(badge => badge.file
      ? <img key={badge.key} src={assets[`../../../../../logo/media-badges/${badge.file}`]} alt={badge.title} title={badge.title} className={`media-badge media-badge-${badge.key}`} draggable={false} />
      : <span key={badge.key} className="rounded bg-black/75 px-1.5 py-0.5 text-xs text-gold">{badge.title}</span>)}
  </div>;
}
