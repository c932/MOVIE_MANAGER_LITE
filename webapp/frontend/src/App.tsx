import { Routes, Route, Navigate } from 'react-router-dom';
import Home from './pages/Home';
import MovieWall from './pages/MovieWall';
import GameWall from './pages/GameWall';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/movie" element={<MovieWall />} />
      <Route path="/game" element={<GameWall />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
