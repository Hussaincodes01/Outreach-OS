"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";
import { api } from "@/lib/api-client";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "failed">("working");
  const [message, setMessage] = useState("");
  // React 18 StrictMode mounts effects twice in development; without this the
  // token would be submitted twice and the second call could look like a
  // failure to the user.
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;
    if (!token) {
      setState("failed");
      setMessage("This link is missing its token.");
      return;
    }
    api
      .verifyEmail(token)
      .then((r) => {
        setState("ok");
        setMessage(r.message);
      })
      .catch((e: Error) => {
        setState("failed");
        setMessage(e.message);
      });
  }, [token]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {state === "ok" && <CheckCircle2 className="h-5 w-5" aria-hidden="true" />}
          {state === "failed" && <XCircle className="h-5 w-5" aria-hidden="true" />}
          {state === "working" && "Confirming…"}
          {state === "ok" && "Email confirmed"}
          {state === "failed" && "Couldn't confirm"}
        </CardTitle>
        <CardDescription>
          {state === "working" ? "One moment." : message}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {state === "ok" && (
          <Link href="/dashboard" className="underline">
            Go to your dashboard
          </Link>
        )}
        {state === "failed" && (
          <p className="text-muted-foreground">
            Links expire after 48 hours. Sign in and request a new one from the
            banner at the top of the app.
          </p>
        )}
        {state !== "working" && (
          <p>
            <Link href="/login" className="underline">
              Back to sign in
            </Link>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmail />
    </Suspense>
  );
}
