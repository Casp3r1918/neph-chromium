"""The "vault" patch of apply.py: Chromium's password store hands its passwords
to Neph's vault instead of the OS key.

Chromium encrypts every saved password with one AES key that Windows DPAPI
unwraps for any process of the logged-in user (LoginDatabase::EncryptedString
and DecryptedString in login_database_win.cc). Neph's vault (src/native/vault.h)
wraps its key with a master password and a TPM-sealed device secret instead.
The seam is exactly those two functions, so the patch is small:

  login_database_win.cc  EncryptedString/DecryptedString call the host's hooks
                         (registered through the exported neph_vault_set_hooks);
                         with no hooks nothing is encrypted or decrypted, so no
                         password can reach the disk under the OS key by accident.
                         An empty password (the "never save" entries) holds no
                         secret and is stored empty. Blobs in Chromium's own
                         format stay readable while the host says so, until the
                         migration below has converted them.
  login_database.cc      the purpose of the call (a page filling, a password being
                         saved, anything else) for the hooks, so the host opens its
                         unlock dialog only for what the user is doing; the registry
                         of open databases, neph_vault_migrate, which converts the
                         remaining old blobs in one transaction on the database's own
                         sequence, and neph_vault_wipe for a reset vault; and a veto on deleting "undecryptable" passwords:
                         with the vault closed every password looks undecryptable,
                         and Chromium would delete them all.
  login_database.h       the declaration of the migration.

The ABI (struct NephVaultHooks, the purposes, the status numbers) is the one in
src/native/vault_hooks.h; change both together.
"""

PASSWORD_STORE = 'components/password_manager/core/browser/password_store/'
WIN_FILE = PASSWORD_STORE + 'login_database_win.cc'
CC_FILE = PASSWORD_STORE + 'login_database.cc'
H_FILE = PASSWORD_STORE + 'login_database.h'
FILES = (WIN_FILE, CC_FILE, H_FILE)


class AnchorMissing(Exception):
    pass


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        raise AnchorMissing('%s: %s (found %d times)' % (what, old.strip().splitlines()[0], text.count(old)))
    return text.replace(old, new, 1)


WIN_BODY = r'''
// Neph vault: password blobs are encrypted by the host's vault (a master
// password plus a TPM-sealed device secret) instead of the OS key. The host
// registers its hooks through neph_vault_set_hooks, exported by libcef, before
// Chromium starts. With no hooks nothing is encrypted and nothing is
// decrypted, so no password can be written under the OS key by accident.
// scripts/chromium-patches/vault_patch.py owns this file; src/native/vault_hooks.h
// holds the same ABI on the host side.

#include "components/password_manager/core/browser/password_store/login_database.h"

#include <windows.h>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "components/os_crypt/async/common/encryptor.h"

extern "C" {
struct NephVaultHooks {
  uint32_t size;
  uint32_t version;
  // 0 ok, otherwise a status of the host's vault; |out_size| is the size
  // written or needed. Buffers belong to the caller.
  int (*encrypt)(const uint8_t* plain, size_t plain_size, uint8_t* out,
                 size_t capacity, size_t* out_size, int purpose);
  int (*decrypt)(const uint8_t* blob, size_t blob_size, uint8_t* out,
                 size_t capacity, size_t* out_size, int purpose);
  // 1 while blobs in Chromium's old format may still be read.
  int (*legacy_allowed)(void);
};
}  // extern "C"

namespace password_manager {

// Defined in login_database.cc: why the store is calling.
int NephVaultPurpose();

namespace {

constexpr int kNephStatusNotVaultBlob = 3;
constexpr int kNephStatusBufferTooSmall = 5;

std::atomic<const NephVaultHooks*> g_neph_hooks{nullptr};

void NephWipe(std::string& text) {
  if (!text.empty()) {
    SecureZeroMemory(text.data(), text.size());
  }
}

void NephWipe(std::vector<uint8_t>& bytes) {
  if (!bytes.empty()) {
    SecureZeroMemory(bytes.data(), bytes.size());
  }
}

}  // namespace

extern "C" __declspec(dllexport) void neph_vault_set_hooks(
    const NephVaultHooks* hooks) {
  g_neph_hooks.store(hooks && hooks->version == 1 &&
                             hooks->size >= sizeof(NephVaultHooks)
                         ? hooks
                         : nullptr);
}

EncryptionResult LoginDatabase::EncryptedString(
    const std::u16string& plain_text,
    std::string* cipher_text) const {
  // An empty password (a "never save" entry, a federated login) holds no
  // secret: it is stored empty, and DecryptedString reads it back as empty.
  if (plain_text.empty()) {
    cipher_text->clear();
    return EncryptionResult::kSuccess;
  }
  const NephVaultHooks* hooks = g_neph_hooks.load();
  if (!hooks) {
    return EncryptionResult::kServiceFailure;
  }
  std::string plain = base::UTF16ToUTF8(plain_text);
  std::vector<uint8_t> out(plain.size() + 64);
  size_t out_size = 0;
  int status = hooks->encrypt(reinterpret_cast<const uint8_t*>(plain.data()),
                              plain.size(), out.data(), out.size(), &out_size,
                              NephVaultPurpose());
  if (status == kNephStatusBufferTooSmall && out_size > out.size()) {
    out.assign(out_size, 0);
    status = hooks->encrypt(reinterpret_cast<const uint8_t*>(plain.data()),
                            plain.size(), out.data(), out.size(), &out_size,
                            NephVaultPurpose());
  }
  NephWipe(plain);
  if (status != 0 || out_size > out.size()) {
    NephWipe(out);
    return EncryptionResult::kServiceFailure;
  }
  cipher_text->assign(reinterpret_cast<const char*>(out.data()), out_size);
  NephWipe(out);
  return EncryptionResult::kSuccess;
}

EncryptionResult LoginDatabase::DecryptedString(
    const std::string& cipher_text,
    std::u16string* plain_text) const {
  // Unittests need to read sample database entries. If these entries had real
  // passwords, their encoding would need to be different for every platform.
  // To avoid the need for that, the entries have empty passwords.
  // os_crypt_async on Windows does not recognise the empty string as a valid
  // encrypted string. Changing that for all clients of os_crypt_async could
  // have too broad an impact, therefore to allow platform-independent data
  // files for LoginDatabase tests, the special handling of the empty string
  // is added below instead.
  // See also https://codereview.chromium.org/2291123008/#msg14 for a
  // discussion.
  if (cipher_text.empty()) {
    plain_text->clear();
    return EncryptionResult::kSuccess;
  }
  const NephVaultHooks* hooks = g_neph_hooks.load();
  if (!hooks) {
    return EncryptionResult::kServiceFailure;
  }
  std::vector<uint8_t> out(cipher_text.size());
  size_t out_size = 0;
  const int status = hooks->decrypt(
      reinterpret_cast<const uint8_t*>(cipher_text.data()), cipher_text.size(),
      out.data(), out.size(), &out_size, NephVaultPurpose());
  if (status == 0 && out_size <= out.size()) {
    *plain_text = base::UTF8ToUTF16(std::string_view(
        reinterpret_cast<const char*>(out.data()), out_size));
    NephWipe(out);
    return EncryptionResult::kSuccess;
  }
  NephWipe(out);
  if (status == kNephStatusNotVaultBlob && hooks->legacy_allowed()) {
    // A password from before the vault, in Chromium's own format: readable
    // until the migration has converted every one of them.
    return encryptor_ && encryptor_->DecryptString16(cipher_text, plain_text)
               ? EncryptionResult::kSuccess
               : EncryptionResult::kServiceFailure;
  }
  return EncryptionResult::kServiceFailure;
}

}  // namespace password_manager
'''

CC_INCLUDES = r'''#include "sql/transaction.h"

// Neph vault: the registry of open databases and the migration run.
#include <atomic>
#include <vector>

#include "base/memory/ref_counted.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/sequenced_task_runner.h"
'''

CC_HELPERS = r'''// Neph vault -----------------------------------------------------------------
// What the store tells the vault hooks about the call it is in (read through
// NephVaultPurpose() by login_database_win.cc): 1 a page asking for passwords
// to fill, 2 a password being saved, 0 anything Chromium does in the
// background. The hooks use it to open the unlock dialog only for what the
// user is doing.
namespace {

thread_local int g_neph_purpose = 0;

class NephPurposeScope {
 public:
  explicit NephPurposeScope(int purpose) : previous_(g_neph_purpose) {
    g_neph_purpose = purpose;
  }
  NephPurposeScope(const NephPurposeScope&) = delete;
  NephPurposeScope& operator=(const NephPurposeScope&) = delete;
  ~NephPurposeScope() { g_neph_purpose = previous_; }

 private:
  const int previous_;
};

bool NephIsVaultBlob(const std::string& blob) {
  return blob.size() >= 3 && blob[0] == 'N' && blob[1] == 'V' && blob[2] == '1';
}

// Neph never lets the store delete a password because it cannot be decrypted:
// with the vault closed that is every password.
bool NephNeverDeleteUndecryptable() {
  return true;
}

// The databases that are open, each with the sequence it lives on: the host
// reaches them through neph_vault_migrate, and a task runs on that sequence.
struct NephDatabaseEntry {
  LoginDatabase* database;
  scoped_refptr<base::SequencedTaskRunner> runner;
};

base::Lock& NephRegistryLock() {
  static base::NoDestructor<base::Lock> lock;
  return *lock;
}

std::vector<NephDatabaseEntry>& NephRegistry() {
  static base::NoDestructor<std::vector<NephDatabaseEntry>> registry;
  return *registry;
}

void NephRegisterDatabase(LoginDatabase* database) {
  if (!base::SequencedTaskRunner::HasCurrentDefault()) {
    return;
  }
  base::AutoLock lock(NephRegistryLock());
  for (const auto& entry : NephRegistry()) {
    if (entry.database == database) {
      return;
    }
  }
  NephRegistry().push_back(
      {database, base::SequencedTaskRunner::GetCurrentDefault()});
}

void NephUnregisterDatabase(LoginDatabase* database) {
  base::AutoLock lock(NephRegistryLock());
  std::erase_if(NephRegistry(), [database](const NephDatabaseEntry& entry) {
    return entry.database == database;
  });
}

}  // namespace

int NephVaultPurpose();
int NephVaultPurpose() {
  return g_neph_purpose;
}

struct LoginDatabase::PrimaryKeyAndPassword {'''

CC_DTOR_NEW = r'''LoginDatabase::~LoginDatabase() {
  NephUnregisterDatabase(this);
}'''

CC_MIGRATION = r'''// Neph vault: converts the passwords that are still in Chromium's own format
// (an OS-key blob) to the vault's. Runs on the database's sequence with the
// vault open (the hooks refuse otherwise), in one transaction, and every new
// blob is read back before it replaces the old one. A password the OS key
// cannot open is counted in |failed| and left as it is; false means nothing
// could be done (database closed, transaction failed).
bool LoginDatabase::NephMigrateLegacyToVault(int* migrated, int* failed) {
  *migrated = 0;
  *failed = 0;
  if (!db_.is_open() || !encryptor_ || !encryptor_->IsEncryptionAvailable()) {
    return false;
  }
  struct Row {
    int id;
    std::string blob;
  };
  const auto collect = [this](base::cstring_view sql) {
    std::vector<Row> rows;
    sql::Statement select(db_.GetUniqueStatement(sql));
    while (select.Step()) {
      std::string blob = select.ColumnBlobAsString(1);
      if (!blob.empty() && !NephIsVaultBlob(blob)) {
        rows.push_back({select.ColumnInt(0), std::move(blob)});
      }
    }
    return rows;
  };
  const std::vector<Row> passwords =
      collect("SELECT id, password_value FROM logins");
  const std::vector<Row> notes =
      db_.DoesTableExist("password_notes")
          ? collect("SELECT id, value FROM password_notes")
          : std::vector<Row>();
  if (passwords.empty() && notes.empty()) {
    return true;
  }
  sql::Transaction transaction(&db_);
  if (!transaction.Begin()) {
    return false;
  }
  const auto convert = [this](const std::string& blob, std::string* fresh) {
    std::u16string plain;
    std::u16string check;
    return encryptor_->DecryptString16(blob, &plain) &&
           EncryptedString(plain, fresh) == EncryptionResult::kSuccess &&
           DecryptedString(*fresh, &check) == EncryptionResult::kSuccess &&
           check == plain;
  };
  for (const Row& row : passwords) {
    std::string fresh;
    if (!convert(row.blob, &fresh)) {
      ++*failed;
      continue;
    }
    sql::Statement update(db_.GetUniqueStatement(
        "UPDATE logins SET password_value = ? WHERE id = ?"));
    update.BindBlob(0, fresh);
    update.BindInt(1, row.id);
    if (!update.Run()) {
      return false;
    }
    ++*migrated;
  }
  for (const Row& row : notes) {
    std::string fresh;
    if (!convert(row.blob, &fresh)) {
      ++*failed;
      continue;
    }
    sql::Statement update(db_.GetUniqueStatement(
        "UPDATE password_notes SET value = ? WHERE id = ?"));
    update.BindBlob(0, fresh);
    update.BindInt(1, row.id);
    if (!update.Run()) {
      return false;
    }
    ++*migrated;
  }
  return transaction.Commit();
}

// Neph vault: the master password is forgotten and the vault is reset, so the
// passwords it protected are gone for good; what is left of them in the
// store would only make every page that has one fail. Entries without a
// password (never save, federated) stay. Database sequence only.
bool LoginDatabase::NephWipePasswords(int* removed) {
  *removed = 0;
  if (!db_.is_open()) {
    return false;
  }
  sql::Statement wipe(db_.GetUniqueStatement(
      "DELETE FROM logins WHERE length(password_value) > 0"));
  if (!wipe.Run()) {
    return false;
  }
  *removed = static_cast<int>(db_.GetLastChangeCount());
  return true;
}

namespace {

// One call of neph_vault_migrate or neph_vault_wipe over every open database;
// the last database to finish reports.
class NephMigrationRun : public base::RefCountedThreadSafe<NephMigrationRun> {
 public:
  NephMigrationRun(void (*done)(void*, int, int, int),
                   void* context,
                   size_t pending)
      : done_(done), context_(context), pending_(pending) {}

  void Finish(bool ok, int migrated, int failed) {
    int status = 0;
    int migrated_total = 0;
    int failed_total = 0;
    {
      base::AutoLock lock(lock_);
      if (!ok) {
        status_ = -2;
      }
      migrated_ += migrated;
      failed_ += failed;
      if (--pending_ != 0) {
        return;
      }
      status = status_;
      migrated_total = migrated_;
      failed_total = failed_;
    }
    done_(context_, status, migrated_total, failed_total);
  }

 private:
  friend class base::RefCountedThreadSafe<NephMigrationRun>;
  ~NephMigrationRun() = default;

  void (*const done_)(void*, int, int, int);
  void* const context_;
  base::Lock lock_;
  size_t pending_;
  int status_ = 0;
  int migrated_ = 0;
  int failed_ = 0;
};

void NephMaintainOne(LoginDatabase* database,
                     bool wipe,
                     scoped_refptr<NephMigrationRun> run) {
  bool open = false;
  {
    base::AutoLock lock(NephRegistryLock());
    for (const auto& entry : NephRegistry()) {
      open = open || entry.database == database;
    }
  }
  int migrated = 0;
  int failed = 0;
  bool ok = false;
  if (open && wipe) {
    ok = database->NephWipePasswords(&migrated);
  } else if (open) {
    ok = database->NephMigrateLegacyToVault(&migrated, &failed);
  }
  run->Finish(ok, migrated, failed);
}

}  // namespace

// status -1: no database is open yet (the host asks again), -2: a database
// could not be done (the vault is closed, the transaction failed). For a wipe
// the first number after the status is how many passwords were deleted.
void NephStartMaintenance(bool wipe,
                          void (*done)(void*, int, int, int),
                          void* context);
void NephStartMaintenance(bool wipe,
                          void (*done)(void*, int, int, int),
                          void* context) {
  std::vector<NephDatabaseEntry> entries;
  {
    base::AutoLock lock(NephRegistryLock());
    entries = NephRegistry();
  }
  if (entries.empty()) {
    done(context, -1, 0, 0);
    return;
  }
  auto run = base::MakeRefCounted<NephMigrationRun>(done, context, entries.size());
  for (const auto& entry : entries) {
    entry.runner->PostTask(
        FROM_HERE,
        base::BindOnce(&NephMaintainOne, entry.database, wipe, run));
  }
}

}  // namespace password_manager

extern "C" __declspec(dllexport) void neph_vault_migrate(
    void (*done)(void*, int, int, int),
    void* context) {
  password_manager::NephStartMaintenance(false, done, context);
}

extern "C" __declspec(dllexport) void neph_vault_wipe(
    void (*done)(void*, int, int, int),
    void* context) {
  password_manager::NephStartMaintenance(true, done, context);
}
'''

H_DECL = r'''  DatabaseCleanupResult DeleteUndecryptableLogins();

  // Neph vault (see login_database.cc), database sequence only: converts the
  // passwords still in Chromium's OS-key format to the vault's; deletes every
  // saved password (the "never save" entries stay) once the vault is reset.
  bool NephMigrateLegacyToVault(int* migrated, int* failed);
  bool NephWipePasswords(int* removed);
'''


def build(pristine):
    """pristine: path -> committed text. Returns path -> patched text."""
    out = {}

    win = pristine[WIN_FILE]
    for needle in ('encryptor_->EncryptString16(plain_text, cipher_text)',
                   'encryptor_->DecryptString16(cipher_text, plain_text)'):
        if needle not in win:
            raise AnchorMissing(WIN_FILE + ': ' + needle)
    header = '\n'.join(win.split('\n')[:3])
    if not header.startswith('// Copyright'):
        raise AnchorMissing(WIN_FILE + ': copyright header')
    out[WIN_FILE] = header + '\n' + WIN_BODY

    cc = pristine[CC_FILE]
    cc = replace_once(cc, '#include "sql/transaction.h"\n', CC_INCLUDES, 'login_database.cc includes')
    cc = replace_once(cc, 'struct LoginDatabase::PrimaryKeyAndPassword {', CC_HELPERS, 'login_database.cc PrimaryKeyAndPassword')
    cc = replace_once(cc, 'LoginDatabase::~LoginDatabase() = default;', CC_DTOR_NEW, 'login_database.cc destructor')
    cc = replace_once(cc, '  TRACE_EVENT0("passwords", "LoginDatabase::Init");\n',
                      '  TRACE_EVENT0("passwords", "LoginDatabase::Init");\n  NephRegisterDatabase(this);\n', 'login_database.cc Init')
    cc = replace_once(cc, '  TRACE_EVENT0("passwords", "LoginDatabase::AddLogin");\n',
                      '  TRACE_EVENT0("passwords", "LoginDatabase::AddLogin");\n  NephPurposeScope neph_purpose(2);\n', 'login_database.cc AddLogin')
    cc = replace_once(cc, '  TRACE_EVENT0("passwords", "LoginDatabase::UpdateLogin");\n',
                      '  TRACE_EVENT0("passwords", "LoginDatabase::UpdateLogin");\n  NephPurposeScope neph_purpose(2);\n', 'login_database.cc UpdateLogin')
    cc = replace_once(cc, '  TRACE_EVENT0("passwords", "LoginDatabase::GetLogins");\n',
                      '  TRACE_EVENT0("passwords", "LoginDatabase::GetLogins");\n  NephPurposeScope neph_purpose(1);\n', 'login_database.cc GetLogins')
    # With the vault closed every password is "undecryptable"; Neph never lets
    # the store delete passwords for that.
    cc = replace_once(
        cc,
        '  if (!encryptor_ || !encryptor_->IsEncryptionAvailable()) {\n'
        '    metrics_util::LogDeleteUndecryptableLoginsReturnValue(\n',
        '  // Neph: never. A closed vault makes every password look undecryptable.\n'
        '  if (NephNeverDeleteUndecryptable() || !encryptor_ ||\n'
        '      !encryptor_->IsEncryptionAvailable()) {\n'
        '    metrics_util::LogDeleteUndecryptableLoginsReturnValue(\n',
        'login_database.cc DeleteUndecryptableLogins')
    tail = '}  // namespace password_manager\n'
    if not cc.endswith(tail):
        raise AnchorMissing('login_database.cc: closing namespace')
    cc = cc[:-len(tail)] + CC_MIGRATION
    out[CC_FILE] = cc

    out[H_FILE] = replace_once(pristine[H_FILE], '  DatabaseCleanupResult DeleteUndecryptableLogins();\n', H_DECL, 'login_database.h')
    return out
