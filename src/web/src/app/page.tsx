import { ThemeWorkspace } from "@/components/ThemeWorkspace";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const themes = await api.listThemes().catch(() => []);
  return <ThemeWorkspace initialThemes={themes} />;
}
