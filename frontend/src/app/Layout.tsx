import { NavLink, Outlet } from 'react-router-dom';
import { navItems } from './routes';

export function Layout() {
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-border bg-surface-muted md:min-h-screen md:w-56 md:border-b-0 md:border-r">
        <div className="px-4 py-3 text-lg font-semibold">LocalETL</div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `whitespace-nowrap rounded px-3 py-2 text-sm ${
                  isActive ? 'bg-primary text-primary-fg' : 'text-fg hover:bg-border/50'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8">
        <Outlet />
      </main>
    </div>
  );
}
