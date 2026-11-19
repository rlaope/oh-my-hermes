export function displayName(user) {
  if (user.nickname == null) {
    return user.fullName;
  }
  return user.nickname;
}
