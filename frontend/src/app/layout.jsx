import { Inter } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });

export const metadata = {
  title: { default: "Gestiona", template: "%s · Gestiona" },
  description: "Gestión de proyectos y trabajo del equipo",
};

const themeScript = `try{var t=localStorage.getItem('gestiona-theme');if(t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.dataset.theme='dark'}}catch(e){}`;

export default function RootLayout({ children }) {
  return (
    <html lang="es" className={inter.variable} suppressHydrationWarning>
      <body className="antialiased">
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
