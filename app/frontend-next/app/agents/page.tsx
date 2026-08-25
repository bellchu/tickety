"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, RefreshCw, Search, ShieldCheck, Trash2, Unlink, UserCog, Users } from "lucide-react";
import { Alert, Badge, Button, ConfirmDialog, DataListCard, DataTable, DataTableViewport, Dialog, EmptyState, ErrorState, IconButton, ListText, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { canAccessAdministration, isDemoContext } from "@/lib/auth";
import type { ExternalUserRecord, UserCreateInput, UserExternalIdentityLink, UserOut } from "@/lib/types";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

const ROLES = [
  { value: "admin", label: "Admin", icon: ShieldCheck, description: "Full platform and access control" },
  { value: "supervisor", label: "Supervisor", icon: UserCog, description: "Queue, team, and reporting oversight" },
  { value: "agent", label: "Agent", icon: Users, description: "Assigned work and ticket updates" },
];

function roleVariant(role: string): "danger" | "warning" | "success" | "neutral" {
  if (role === "admin") return "danger";
  if (role === "supervisor") return "warning";
  if (role === "agent") return "success";
  return "neutral";
}

function initials(name: string) {
  return name.split(" ").filter(Boolean).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManageUsers = canAccessAdministration(authQuery.data);
  const isDemoMode = isDemoContext(authQuery.data);
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: api.getUsers, enabled: canManageUsers });
  const identityLinksQuery = useQuery({ queryKey: ["agent-identity-links"], queryFn: () => api.getAgentIdentityLinks(), enabled: canManageUsers });
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [deactivating, setDeactivating] = useState<UserOut | null>(null);
  const [purging, setPurging] = useState<UserOut | null>(null);
  const [linking, setLinking] = useState<UserOut | null>(null);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (payload: UserCreateInput) => api.createUser(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
      setFormOpen(false);
      setNotice("Agent access created successfully.");
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<UserCreateInput> }) => api.updateUser(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      setEditing(null);
      setNotice("Agent profile updated.");
    },
  });
  const deactivateMutation = useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      setDeactivating(null);
      setNotice("Agent access deactivated.");
    },
  });
  const purgeMutation = useMutation({
    mutationFn: (id: string) => api.purgeUser(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
      setPurging(null);
      setNotice("Deactivated account permanently purged.");
    },
  });
  const setIdentityMutation = useMutation({
    mutationFn: ({ userId, externalUserId }: { userId: string; externalUserId: string }) => api.setAgentIdentityLink(userId, externalUserId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-identity-links"] });
      setLinking(null);
      setNotice("Freshservice work identity linked. Personal and team inboxes will use provider-authoritative assignment.");
    },
  });
  const deleteIdentityMutation = useMutation({
    mutationFn: ({ userId, linkId }: { userId: string; linkId: number }) => api.deleteAgentIdentityLink(userId, linkId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-identity-links"] });
      setNotice("Freshservice work identity unlinked.");
    },
  });

  const linksByUser = useMemo(() => {
    const result = new Map<string, UserExternalIdentityLink[]>();
    for (const link of identityLinksQuery.data || []) {
      result.set(link.user_id, [...(result.get(link.user_id) || []), link]);
    }
    return result;
  }, [identityLinksQuery.data]);

  const activeUsers = useMemo(() => (usersQuery.data ?? []).filter((user) => user.is_active), [usersQuery.data]);
  const inactiveUsers = useMemo(() => (usersQuery.data ?? []).filter((user) => !user.is_active), [usersQuery.data]);
  const filteredUsers = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return activeUsers;
    return activeUsers.filter((user) => [user.name, user.email ?? "", user.title ?? "", user.role].some((value) => value.toLowerCase().includes(term)));
  }, [activeUsers, search]);
  const filteredInactiveUsers = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return inactiveUsers;
    return inactiveUsers.filter((user) => [user.name, user.email ?? "", user.title ?? "", user.role].some((value) => value.toLowerCase().includes(term)));
  }, [inactiveUsers, search]);
  const retrying = usersQuery.isFetching && !usersQuery.isLoading;

  if (authQuery.isLoading) {
    return <div className="mx-auto max-w-7xl space-y-6" aria-busy="true" aria-label="Checking user management access"><Skeleton className="h-28 w-full" /><Skeleton className="h-80 w-full" /></div>;
  }

  if (authQuery.isError) {
    return <ErrorState title="User management access could not be checked" description="Your session could not be verified, so no user account data was requested." actionLabel="Retry access check" onRetry={() => void authQuery.refetch()} retrying={authQuery.isFetching} />;
  }

  if (!canManageUsers) {
    return <EmptyState className="mx-auto min-h-72 max-w-2xl" icon={<ShieldCheck className="h-5 w-5" />} title={isDemoMode ? "Demo administrator access required" : "Administrator access required"} description={isDemoMode ? "Sign in with an active demo administrator account to manage users, roles, and access." : "Only active administrators can manage users, roles, and access."} />;
  }

  return (
    <PageFrame>
      <PageHeader eyebrow="Team operations" icon={<Users className="h-4 w-4" />} title="Agents" description="Manage operational roles, access, and team capacity from one controlled roster." actions={<Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { createMutation.reset(); setFormOpen(true); }}>Add agent</Button>} />

      {notice && <Alert variant="success" title="Saved" action={<Button size="sm" variant="ghost" onClick={() => setNotice(null)}>Dismiss</Button>}>{notice}</Alert>}

      <section aria-label="Role coverage" className="grid gap-3 sm:grid-cols-3">
        {ROLES.map(({ value, label, icon: Icon, description }) => (
          <div key={value} className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-linen-200 text-ink-500"><Icon className="h-4 w-4" aria-hidden="true" /></span>
              <span className="text-2xl font-semibold tabular-nums text-ink-700">{activeUsers.filter((user) => user.role === value).length}</span>
            </div>
            <p className="mt-4 text-sm font-semibold text-ink-700">{label}</p>
            <p className="mt-1 text-xs leading-5 text-ink-500">{description}</p>
          </div>
        ))}
      </section>

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm">
        <div className="flex flex-col gap-3 border-b border-linen-400 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-700">Active roster</h2>
            <p className="mt-1 text-xs text-ink-500">{activeUsers.length} active · {filteredUsers.length} shown</p>
          </div>
          <label className="relative block w-full sm:w-72">
            <span className="sr-only">Search agents</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
            <input className="input-base input-search w-full" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, role, or title" />
          </label>
        </div>

        {usersQuery.isLoading ? (
          <div className="space-y-3 p-5" aria-label="Loading agents">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}</div>
        ) : usersQuery.isError ? (
          <ErrorState className="m-5" title="The roster could not be loaded" description="No access changes were made. Check the service connection and try again." onRetry={() => void usersQuery.refetch()} retrying={retrying} />
        ) : filteredUsers.length === 0 ? (
          <EmptyState className="m-5" icon={<Users className="h-5 w-5" />} title={search ? "No agents match this search" : "No active agents"} description={search ? "Try a name, role, email address, or title." : "Add an agent to begin assigning operational work."} action={search ? <Button variant="secondary" onClick={() => setSearch("")}>Clear search</Button> : <Button onClick={() => setFormOpen(true)}>Add agent</Button>} />
        ) : (
          <>
            <div className="grid gap-3 bg-linen-100/60 p-3 md:hidden">
              {filteredUsers.map((user) => <AgentCard key={user.id} user={user} links={linksByUser.get(user.id) || []} onLink={() => { setIdentityMutation.reset(); setLinking(user); }} onEdit={() => { updateMutation.reset(); setEditing(user); }} onDeactivate={() => setDeactivating(user)} />)}
            </div>
            <DataTableViewport label="Active agent roster" className="hidden md:block">
              <DataTable className="min-w-[840px]">
                <colgroup><col className="w-[28%]" /><col className="w-[14%]" /><col className="w-[17%]" /><col className="w-[23%]" /><col className="w-[8%]" /><col className="w-[10%]" /></colgroup>
                <thead className="bg-linen-100 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">
                  <tr><th className="px-5 py-3" scope="col">Agent</th><th className="px-4 py-3" scope="col">Access</th><th className="px-4 py-3" scope="col">Title</th><th className="px-4 py-3" scope="col">Work identity</th><th className="px-4 py-3 text-right" scope="col">Impact</th><th className="px-5 py-3 text-right" scope="col"><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody className="divide-y divide-linen-300">
                  {filteredUsers.map((user) => (
                    <tr key={user.id} className="transition-colors hover:bg-linen-100">
                      <td className="px-5 py-4"><AgentIdentity user={user} /></td>
                      <td className="px-4 py-4"><Badge variant={roleVariant(user.role)} dot>{user.role}</Badge><span className="mt-2 block text-[11px] font-medium text-ink-400">Tier {user.tier}</span></td>
                      <td className="px-4 py-4"><ListText text={user.title || "Not set"} lines={2} className="text-xs text-ink-500" /></td>
                      <td className="px-4 py-4"><WorkIdentity links={linksByUser.get(user.id) || []} /></td>
                      <td className="px-4 py-4 text-right font-medium tabular-nums text-ink-700">{user.impact_points.toLocaleString()}</td>
                      <td className="px-5 py-4"><div className="flex justify-end gap-1"><IconButton size="sm" aria-label={`Link work identity for ${user.name}`} icon={<Link2 className="h-4 w-4" />} onClick={() => { setIdentityMutation.reset(); setLinking(user); }} /><IconButton size="sm" aria-label={`Edit ${user.name}`} icon={<UserCog className="h-4 w-4" />} onClick={() => { updateMutation.reset(); setEditing(user); }} /><IconButton size="sm" aria-label={`Deactivate ${user.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => setDeactivating(user)} /></div></td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </DataTableViewport>
          </>
        )}
      </section>

      <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm" aria-label="Deactivated accounts">
        <div className="border-b border-linen-400 p-4">
          <h2 className="text-sm font-semibold text-ink-700">Deactivated accounts</h2>
          <p className="mt-1 text-xs text-ink-500">{inactiveUsers.length} deactivated · {filteredInactiveUsers.length} shown. Purging permanently removes the account and its authentication data.</p>
        </div>
        {usersQuery.isLoading ? (
          <div className="space-y-3 p-5"><Skeleton className="h-14 w-full" /></div>
        ) : filteredInactiveUsers.length === 0 ? (
          <EmptyState className="m-5" icon={<Users className="h-5 w-5" />} title={search ? "No deactivated accounts match this search" : "No deactivated accounts"} description={search ? "Try another name, role, email address, or title." : "Accounts will appear here after their access is deactivated."} />
        ) : (
          <div className="divide-y divide-linen-300">
            {filteredInactiveUsers.map((user) => (
              <div key={user.id} className="flex min-w-0 flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1 opacity-75"><AgentIdentity user={user} /></div>
                <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                  <Badge variant="neutral">Deactivated</Badge>
                  <Badge variant={roleVariant(user.role)}>{user.role}</Badge>
                  <Button size="sm" variant="destructive" leadingIcon={<Trash2 className="h-4 w-4" />} onClick={() => { purgeMutation.reset(); setPurging(user); }}>Purge</Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <UserFormDialog open={formOpen || Boolean(editing)} user={editing} demoMode={isDemoMode} onOpenChange={(open) => { if (!open) { setFormOpen(false); setEditing(null); createMutation.reset(); updateMutation.reset(); } }} onSubmit={(payload) => editing ? updateMutation.mutate({ id: editing.id, payload }) : createMutation.mutate(payload)} pending={createMutation.isPending || updateMutation.isPending} error={createMutation.error || updateMutation.error} />
      <WorkIdentityDialog user={linking} existingLinks={linking ? linksByUser.get(linking.id) || [] : []} allLinks={identityLinksQuery.data || []} onOpenChange={(open) => { if (!open) { setLinking(null); setIdentityMutation.reset(); } }} onSubmit={(externalUserId) => linking && setIdentityMutation.mutate({ userId: linking.id, externalUserId })} onUnlink={(linkId) => linking && deleteIdentityMutation.mutate({ userId: linking.id, linkId })} pending={setIdentityMutation.isPending || deleteIdentityMutation.isPending} error={setIdentityMutation.error || deleteIdentityMutation.error} />
      <ConfirmDialog open={Boolean(deactivating)} onOpenChange={(open) => { if (!open) { setDeactivating(null); deactivateMutation.reset(); } }} title="Deactivate agent access?" description={`${deactivating?.name ?? "This agent"} will no longer appear in the active roster or receive new assignments. Historical work remains available.`} confirmLabel="Deactivate agent" destructive pending={deactivateMutation.isPending} onConfirm={() => { if (deactivating) deactivateMutation.mutate(deactivating.id); }} />
      {deactivateMutation.isError && <Alert variant="danger" title="Deactivation failed">{deactivateMutation.error instanceof Error ? deactivateMutation.error.message : "Please try again."}</Alert>}
      <ConfirmDialog open={Boolean(purging)} onOpenChange={(open) => { if (!open) { setPurging(null); purgeMutation.reset(); } }} title="Permanently purge this account?" description={`${purging?.name ?? "This user"} and all sign-in data, SSO links, recognitions, approvals, and time entries owned by the account will be permanently removed. Historical records with optional attribution will remain but will no longer identify this user. This cannot be undone.`} confirmLabel="Permanently purge" destructive pending={purgeMutation.isPending} onConfirm={() => { if (purging) purgeMutation.mutate(purging.id); }} />
      {purgeMutation.isError && <Alert variant="danger" title="Account purge failed">{purgeMutation.error instanceof Error ? purgeMutation.error.message : "Please try again."}</Alert>}
    </PageFrame>
  );
}

function AgentIdentity({ user }: { user: UserOut }) {
  return <div className="flex min-w-0 items-center gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-ink-700 text-xs font-semibold text-white">{initials(user.name)}</span><span className="min-w-0"><ListText text={user.name} lines={1} className="font-semibold text-ink-700" /><ListText text={user.email || "No email"} lines={1} className="text-xs text-ink-400" /></span></div>;
}

function WorkIdentity({ links }: { links: UserExternalIdentityLink[] }) {
  if (!links.length) return <span className="text-xs text-ink-400">Not linked</span>;
  return <div className="space-y-1">{links.map((link) => <div key={link.id} className="min-w-0"><ListText text={link.external_name} lines={1} className="text-xs font-semibold text-ink-600" /><ListText text={`${link.provider} · ${link.external_email || link.external_id}`} lines={1} className="text-[10px] text-ink-400" /></div>)}</div>;
}

function AgentCard({ user, links, onLink, onEdit, onDeactivate }: { user: UserOut; links: UserExternalIdentityLink[]; onLink: () => void; onEdit: () => void; onDeactivate: () => void }) {
  return <DataListCard><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0 flex-1"><AgentIdentity user={user} /></div><div className="flex shrink-0 gap-1"><IconButton size="sm" aria-label={`Link work identity for ${user.name}`} icon={<Link2 className="h-4 w-4" />} onClick={onLink} /><IconButton size="sm" aria-label={`Edit ${user.name}`} icon={<UserCog className="h-4 w-4" />} onClick={onEdit} /><IconButton size="sm" aria-label={`Deactivate ${user.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={onDeactivate} /></div></div><div className="mt-4 flex flex-wrap items-center gap-2 border-t border-linen-300 pt-3"><Badge variant={roleVariant(user.role)} dot>{user.role}</Badge><Badge>T{user.tier}</Badge><span className="text-xs whitespace-nowrap text-ink-500">{user.impact_points.toLocaleString()} impact</span><ListText text={user.title || "Title not set"} lines={2} className="w-full text-xs text-ink-500 xs:w-auto xs:max-w-[15rem]" /></div><div className="mt-3 border-t border-linen-300 pt-3"><p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">Work identity</p><WorkIdentity links={links} /></div></DataListCard>;
}

function WorkIdentityDialog({ user, existingLinks, allLinks, onOpenChange, onSubmit, onUnlink, pending, error }: { user: UserOut | null; existingLinks: UserExternalIdentityLink[]; allLinks: UserExternalIdentityLink[]; onOpenChange: (open: boolean) => void; onSubmit: (externalUserId: string) => void; onUnlink: (linkId: number) => void; pending: boolean; error: unknown }) {
  const [selected, setSelected] = useState(existingLinks[0]?.external_user_id || "");
  const externalQuery = useQuery({ queryKey: ["external-users", "agent-identity-picker"], queryFn: () => api.getExternalUsers({ userType: "agent", limit: 200 }), enabled: Boolean(user) });
  const syncMutation = useMutation({ mutationFn: api.syncExternalUsers, onSuccess: () => void externalQuery.refetch() });
  const claimedByOther = new Set(allLinks.filter((link) => link.user_id !== user?.id).map((link) => link.external_user_id));
  const choices = (externalQuery.data?.users || []).filter((external) => !claimedByOther.has(external.id));
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : null;
  return <Dialog key={user?.id || "closed"} open={Boolean(user)} onOpenChange={onOpenChange} title="Link Freshservice work identity" description={`Map ${user?.name || "this user"} to an explicit provider agent identity. Tickety never guesses this mapping from email.`} dismissible={!pending} closeOnBackdrop={!pending} footer={<><Button variant="secondary" disabled={pending} onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!selected || pending} pending={pending} pendingLabel="Linking…" onClick={() => onSubmit(selected)}>Link identity</Button></>}>
    <div className="space-y-4">
      {errorMessage && <Alert variant="danger" title="Identity was not changed">{errorMessage}</Alert>}
      {existingLinks.length > 0 && <section><p className="text-xs font-semibold text-ink-600">Current mappings</p><div className="mt-2 space-y-2">{existingLinks.map((link) => <div key={link.id} className="flex items-center justify-between gap-3 rounded-lg border border-linen-300 bg-linen-100 px-3 py-2"><WorkIdentity links={[link]} /><IconButton size="sm" variant="ghost" disabled={pending} aria-label={`Unlink ${link.external_name}`} icon={<Unlink className="h-4 w-4" />} onClick={() => onUnlink(link.id)} /></div>)}</div></section>}
      <Field label="Freshservice agent" required><select className="input-base" value={selected} onChange={(event) => setSelected(event.target.value)} disabled={externalQuery.isLoading || pending}><option value="">{externalQuery.isLoading ? "Loading provider agents…" : "Select an agent identity"}</option>{choices.map((external: ExternalUserRecord) => <option key={external.id} value={external.id}>{external.name} · {external.email || external.external_id}</option>)}</select></Field>
      {externalQuery.isError && <Alert variant="warning" title="Provider agents unavailable">Refresh the directory after confirming the Freshservice integration is healthy.</Alert>}
      {!externalQuery.isLoading && !externalQuery.isError && choices.length === 0 && <Alert variant="info" title="No unlinked provider agents">Refresh the directory to retrieve current Freshservice agents and group memberships.</Alert>}
      <Button size="sm" variant="secondary" leadingIcon={<RefreshCw className="h-3.5 w-3.5" />} pending={syncMutation.isPending} pendingLabel="Refreshing…" onClick={() => syncMutation.mutate()}>Refresh provider directory</Button>
      {syncMutation.isError && <p className="text-xs text-semantic-danger">{syncMutation.error instanceof Error ? syncMutation.error.message : "Directory refresh failed."}</p>}
    </div>
  </Dialog>;
}

function UserFormDialog({ open, user, demoMode, onOpenChange, onSubmit, pending, error }: { open: boolean; user: UserOut | null; demoMode: boolean; onOpenChange: (open: boolean) => void; onSubmit: (payload: UserCreateInput) => void; pending: boolean; error: unknown }) {
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [title, setTitle] = useState(user?.title ?? "");
  const [role, setRole] = useState(user?.role ?? "agent");
  const [password, setPassword] = useState("");
  const key = user?.id ?? "new";
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : null;
  return <Dialog key={key} open={open} onOpenChange={onOpenChange} title={user ? "Edit agent" : "Add agent"} description={user ? "Update this agent’s profile and access role." : "Create an operational account. Required fields are marked."} dismissible={!pending} closeOnBackdrop={!pending} footer={<><Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button><Button onClick={() => onSubmit({ name: name.trim(), email: email.trim(), title: title.trim() || undefined, role, password: password || undefined })} pending={pending} pendingLabel={user ? "Saving…" : "Creating…"} disabled={!name.trim() || !email.trim()}>{user ? "Save changes" : "Create agent"}</Button></>}>
    <div className="space-y-4">{errorMessage && <Alert variant="danger" title="Changes were not saved">{errorMessage}</Alert>}<Field label="Name" required><input className="input-base" autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} required /></Field><Field label="Email" required><input className="input-base" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></Field><Field label="Title"><input className="input-base" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Support engineer" /></Field><Field label="Role" required><select className="input-base" value={role} onChange={(event) => setRole(event.target.value)}>{ROLES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>{(!user || !demoMode) && <Field label={user ? "New password" : "Password"} hint={user ? "Leave blank to keep the current password." : "Leave blank to let the service generate a password."}><input className="input-base" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field>}{user && demoMode && <p className="rounded-lg border border-linen-400 bg-linen-100 px-3 py-2 text-xs leading-5 text-ink-500">Password changes are unavailable in demo mode. You can still update this account’s profile, role, and access status.</p>}</div>
  </Dialog>;
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return <label className="block"><span className="text-sm font-medium text-ink-700">{label}{required && <span className="text-semantic-danger"> *</span>}</span>{hint && <span className="mt-0.5 block text-xs text-ink-400">{hint}</span>}<span className="mt-2 block">{children}</span></label>;
}
