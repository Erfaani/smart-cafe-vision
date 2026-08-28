import { redirect } from "next/navigation";

import { getAccessToken, getRefreshToken } from "@/lib/session";

export default async function Home() {
  const signedIn = (await getAccessToken()) ?? (await getRefreshToken());
  redirect(signedIn ? "/dashboard" : "/login");
}
