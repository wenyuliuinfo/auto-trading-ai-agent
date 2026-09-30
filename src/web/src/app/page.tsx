import { ThemeWorkspace } from "@/components/ThemeWorkspace";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [themes, subExposures] = await Promise.all([
    api.listThemes().catch(() => []),
    api.listSubExposures().catch(() => []),
  ]);
  return <ThemeWorkspace initialThemes={themes} subExposures={subExposures} />;
}
