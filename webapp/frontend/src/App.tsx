import { Routes, Route, Navigate } from 'react-router-dom';
import MovieWall from './pages/MovieWall';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<MovieWall />} />
      <Route path="/movie" element={<MovieWall />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
