"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SocialButtons } from "@/components/auth/social-buttons";

const schema = z.object({
  tenantName: z.string().min(1, "workspace name is required").max(200),
  tenantSlug: z
    .string()
    .min(2)
    .max(63)
    .regex(/^[a-z0-9][a-z0-9-]*[a-z0-9]$/, "lowercase letters, digits, and dashes only")
    .optional()
    .or(z.literal("")),
  email: z.string().email(),
  password: z
    .string()
    .min(12, "minimum 12 characters")
    .max(128),
});
type FormValues = z.infer<typeof schema>;

export default function SignupPage() {
  const { signUp } = useAuth();
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    setSubmitting(true);
    try {
      await signUp({
        email: values.email,
        password: values.password,
        tenantName: values.tenantName,
        tenantSlug: values.tenantSlug || undefined,
      });
      toast.success("Workspace created");
      router.push("/dashboard");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create your workspace</CardTitle>
        <CardDescription>
          A new tenant is created and you become its owner. Email + password only — no card required.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-4">
          {/* Social signup skips the form entirely — we get a verified address
              and provision the workspace from the sign-in callback. */}
          <SocialButtons action="Sign up" />
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tenantName">Workspace name</Label>
            <Input id="tenantName" placeholder="Acme Inc." {...register("tenantName")} />
            {errors.tenantName && (
              <p className="text-xs text-destructive">{errors.tenantName.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tenantSlug">URL slug (optional)</Label>
            <Input id="tenantSlug" placeholder="acme" {...register("tenantSlug")} />
            {errors.tenantSlug && (
              <p className="text-xs text-destructive">{errors.tenantSlug.message}</p>
            )}
            <p className="text-xs text-muted-foreground">
              Used in your tenant URL. Lowercase, dashes, digits only.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" {...register("email")} />
            {errors.email && (
              <p className="text-xs text-destructive">{errors.email.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              {...register("password")}
            />
            {errors.password && (
              <p className="text-xs text-destructive">{errors.password.message}</p>
            )}
            <p className="text-xs text-muted-foreground">Minimum 12 characters.</p>
          </div>
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Creating…" : "Create workspace"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="underline">
              Sign in
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
