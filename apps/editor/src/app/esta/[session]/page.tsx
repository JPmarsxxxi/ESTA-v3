"use client";

import { useParams } from "next/navigation";
import { EstaWorkspace } from "@/esta/workspace";

export default function EstaSessionPage() {
	const params = useParams();
	return <EstaWorkspace session={decodeURIComponent(String(params.session))} />;
}
