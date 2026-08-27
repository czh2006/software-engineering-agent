import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
    title: "AI Software Engineering Agent",
    description: "AI Software Engineering Agent — Full Stack",
};

export default function RootLayout({
    children,
}: Readonly<{
    children: ReactNode;
}>) {
    return (
        <html lang="zh-CN" suppressHydrationWarning>
            <body>
                <Providers>{children}</Providers>
            </body>
        </html>
    );
}
