import { Logo } from "@/components/icons";

export default function AuthLayout({ children }) {
  return (
    <div className="flex min-h-full flex-col items-center bg-bg-subtle px-4 py-12">
      <div className="mb-8"><Logo size={36} /></div>
      <div className="w-full max-w-[400px] rounded-[3px] bg-bg px-10 py-8 shadow-[0_0_10px_rgba(9,30,66,0.1)]">
        {children}
      </div>
      <p className="mt-6 text-xs text-fg-subtlest">Gestiona · Herramienta interna del equipo</p>
    </div>
  );
}
