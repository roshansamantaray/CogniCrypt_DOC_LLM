package de.upb.userstudy;

import java.nio.charset.StandardCharsets;
import java.security.InvalidAlgorithmParameterException;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.util.Base64;

import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;

public class StringEncryption {

	// Fixed demo salt for key derivation (not suitable for production).
	public static final byte[] salt = { (byte) 43, (byte) 76, (byte) 95, (byte) 7, (byte) 17 };

	/**
	 * Demo entry point: encrypts a hard-coded string and prints the ciphertext.
	 */
	public static void main(String[] args)
			throws InvalidKeyException, NoSuchAlgorithmException, InvalidKeySpecException, NoSuchPaddingException, InvalidAlgorithmParameterException, BadPaddingException, IllegalBlockSizeException {

		String password = "password";
		String plaintext = "Encrypt me!";
		String ciphertext = encrypt(password, plaintext );
		System.out.println(ciphertext);
	}

	/**
	 * Derive a key from the password and encrypt the plaintext with AES/GCM.
	 */
	public static String encrypt(String pass, String plaintext)
			throws NoSuchAlgorithmException, InvalidKeySpecException, NoSuchPaddingException, InvalidKeyException, InvalidAlgorithmParameterException, BadPaddingException, IllegalBlockSizeException {

		// Derive a key from password+salt (PBKDF2).
		PBEKeySpec keySpec = new PBEKeySpec(pass.toCharArray(), salt, 6500, 256);
		SecretKeyFactory secretKeyFactory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
		SecretKey key = secretKeyFactory.generateSecret(keySpec);

		// Generate a fresh nonce/IV for GCM.
		final byte[] nonce = new byte[32];
		SecureRandom random = SecureRandom.getInstanceStrong();
		random.nextBytes(nonce);
		GCMParameterSpec spec = new GCMParameterSpec(128, nonce);

		// Encrypt using AES/GCM and return Base64-encoded ciphertext.
		Cipher cipher = Cipher.getInstance("AES/GCM/PKCS5Padding");
		cipher.init(Cipher.ENCRYPT_MODE, key, spec);
		byte[] plainTextBytes = plaintext.getBytes(StandardCharsets.UTF_8);
		byte[] cipherTextBytes = cipher.doFinal(plainTextBytes);
		return Base64.getEncoder().encodeToString(cipherTextBytes);
	}

}
