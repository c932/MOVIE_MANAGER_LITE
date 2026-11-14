# Movie Manager Lite 界面约定

本次仅拆分项目，沿用已有海报墙布局、Tailwind 主题与交互。
前端入口为 `src/pages/MovieWall.tsx`，根路径与 `/movie` 指向同一页面。
领域组件由 `src/components/movie/` 维护；API 与类型由 `src/api/client.ts`、`src/types/api.ts` 维护。
后台任务沿用 `useJobPoll` 与 `JobProgress`；数据加载、空列表、错误与设置交互保持已有实现。
桌面主题位于 `styles/style.qss`，共享 Qt 布局在本项目内维护。
