import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {TechBadges} from '../components/movie/TechBadges';
import {technologyBadges} from '../utils/mediaBadges';

describe('共享视频格式图标', () => {
  it('分辨率别名及 HDR/DV 组合保持正确能力标识', () => {
    expect(technologyBadges('2160p', 'Dolby Vision / HDR10').map(b => b.key)).toEqual(['4k','hdr','dolbyvision']);
    expect(technologyBadges('', 'DV').map(b => b.key)).toEqual(['dolbyvision']);
    expect(technologyBadges('576p','SDR').map(b => b.file)).toEqual([undefined,undefined]);
    expect(technologyBadges()).toEqual([]);
  });
  it('海报和详情采用同一资源，保留原始格式说明', () => {
    const {rerender} = render(<TechBadges resolution="4K" hdrType="HDR10+" compact />);
    const src = screen.getByRole('img', {name:'4K'}).getAttribute('src');
    expect(src).toMatch(/^data:image\/svg\+xml|4k.*\.svg/);
    expect(screen.getByRole('img', {name:'HDR10+'}).getAttribute('src')).toMatch(/hdr\.png/);
    rerender(<TechBadges resolution="4K" hdrType="HDR10+" />);
    expect(screen.getByRole('img', {name:'4K'}).getAttribute('src')).toBe(src);
  });
});
