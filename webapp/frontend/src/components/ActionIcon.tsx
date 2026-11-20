import type { LucideIcon } from 'lucide-react';

export function ActionIcon({ icon: Icon, className = '' }: { icon: LucideIcon; className?: string }) {
  return <Icon className={`action-icon ${className}`} aria-hidden="true" focusable="false" />;
}
