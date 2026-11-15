import {memo, useLayoutEffect, useRef, useState} from 'react';
import {MovieCard} from './MovieCard';
import type {MovieListItem} from '../../types/api';

interface Props {
  movies: MovieListItem[];
  scale: number;
  selectedId: string | null;
  posterVersion: number;
  onSelect: (movie: MovieListItem) => void;
  onContextMenu: (movie: MovieListItem, x: number, y: number) => void;
  children?: React.ReactNode;
}

/** 保留完整滚动高度，仅绘制视口及前后两行；滚动状态不传回整页。 */
export const VirtualPosterGrid = memo(function VirtualPosterGrid({movies, scale, selectedId, posterVersion, onSelect, onContextMenu, children}: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const [size, setSize] = useState({width: Math.max(320, window.innerWidth - 240), height: Math.max(300, window.innerHeight - 180)});
  const [scrollTop, setScrollTop] = useState(0);
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const measure = () => setSize(previous => {
      const width = element.clientWidth || previous.width;
      const height = element.clientHeight || previous.height;
      return previous.width === width && previous.height === height ? previous : {width, height};
    });
    measure();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    observer?.observe(element);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); cancelAnimationFrame(frame.current); };
  }, []);
  const width = Math.min(Math.round(200 * scale / 100), Math.max(80, size.width - 24));
  const height = Math.round(width * 1.5);
  const columns = Math.max(1, Math.floor((size.width - 24 + 12) / (width + 12)));
  const rows = Math.ceil(movies.length / columns);
  const stride = height + 12;
  const total = Math.max(0, rows * stride - 12) + 24;
  // 筛选缩短结果后立即绘制末端可见行，浏览器会将实际 scrollTop 限制到新高度。
  const top = Math.min(scrollTop, Math.max(0, total - size.height));
  const start = Math.max(0, Math.floor((top - 12) / stride) - 2) * columns;
  const end = Math.min(movies.length, (Math.ceil((top + size.height) / stride) + 2) * columns);
  return <div ref={viewport} data-testid="poster-scroll" className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
    onScroll={event => {
      const value = event.currentTarget.scrollTop;
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => setScrollTop(value));
    }}>
    {children}
    <div role="group" aria-label="电影海报" className="relative" style={{height: movies.length ? total : 0}}>
      {movies.slice(start, end).map((movie, offset) => {
        const index = start + offset;
        return <div key={movie.id} className="absolute" style={{left:12 + index % columns * (width + 12), top:12 + Math.floor(index / columns) * stride, width, height}}>
          <MovieCard movie={movie} width={width} height={height} scale={100} posterVersion={posterVersion} selected={movie.id === selectedId} onSelect={onSelect} onContextMenu={onContextMenu}/>
        </div>;
      })}
    </div>
  </div>;
});
