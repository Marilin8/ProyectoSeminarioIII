-- MySQL dump 10.13  Distrib 8.0.43, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: clinica_imagenes_main
-- ------------------------------------------------------
-- Server version	8.0.43

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `bitacora`
--

DROP TABLE IF EXISTS `bitacora`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bitacora` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username_intento` varchar(150) NOT NULL,
  `accion` varchar(30) NOT NULL,
  `descripcion` longtext NOT NULL,
  `ip` char(39) DEFAULT NULL,
  `creado_en` datetime(6) NOT NULL,
  `usuario_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `bitacora_usuario_id_e2ff0964_fk_usuarios_id` (`usuario_id`),
  CONSTRAINT `bitacora_usuario_id_e2ff0964_fk_usuarios_id` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=143 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `bitacora`
--

LOCK TABLES `bitacora` WRITE;
/*!40000 ALTER TABLE `bitacora` DISABLE KEYS */;
INSERT INTO `bitacora` VALUES (1,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-20 21:04:37.563614',3),(2,'Marilin','login_fallido','Intento de inicio de sesión fallido para \"Marilin\".','127.0.0.1','2026-08-20 21:05:08.044266',4),(3,'marilin','login_fallido','Intento de inicio de sesión fallido para \"marilin\".','127.0.0.1','2026-08-20 21:05:24.297751',4),(4,'marilin','login_exitoso','Inicio de sesión de \"marilin\".','127.0.0.1','2026-08-20 21:05:36.048089',4),(5,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-20 21:06:08.826757',3),(6,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".','127.0.0.1','2026-08-20 21:30:02.841892',NULL),(7,'','solicitar_cita','Registró al paciente Prueba Calendario (DPI 9999999999999) y solicitó cita de Resonancia (prueba 2h) para 2026-08-21 07:00:00 (coex), asignada a radiologo_prueba.','127.0.0.1','2026-08-20 21:32:51.393311',NULL),(8,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-20 21:35:45.898030',3),(9,'','solicitar_cita','Registró al paciente Rodrigro Perez (DPI 2545340000000) y solicitó cita de Rayos X pie para 2026-08-21 09:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-20 21:51:05.170063',3),(10,'','solicitar_cita','Registró al paciente Antony Gordon (DPI 8895000154578) y solicitó cita de Rayos X pie para 2026-08-21 07:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-20 21:53:05.162135',3),(11,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-20 21:54:08.421012',7),(12,'','confirmar_cita','Confirmó la cita de Antony Gordon (8895000154578) para el 2026-08-21 a las 07:00 (cita #21).','127.0.0.1','2026-08-20 21:54:20.114705',7),(13,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-20 21:54:36.076671',3),(14,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".','127.0.0.1','2026-08-21 22:04:44.478506',NULL),(15,'','solicitar_cita','Registró al paciente Prueba PruebaVeinte (DPI 8888888888888) y solicitó cita de Rayos X de columna lumbar para 2026-08-24 10:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-21 22:07:53.619924',NULL),(16,'','solicitar_cita','Registró al paciente Vitor Perez (DPI 8855205499799) y solicitó cita de TAC de cráneo para 2026-08-22 07:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-21 22:14:30.412529',3),(17,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".','127.0.0.1','2026-08-21 22:19:16.392903',NULL),(18,'Marilin','login_fallido','Intento de inicio de sesión fallido para \"Marilin\".','127.0.0.1','2026-08-21 22:42:29.776085',4),(19,'Marilin','login_fallido','Intento de inicio de sesión fallido para \"Marilin\".','127.0.0.1','2026-08-21 22:42:40.409101',4),(20,'marilin','login_fallido','Intento de inicio de sesión fallido para \"marilin\".','127.0.0.1','2026-08-21 22:42:56.174527',4),(21,'marilin','login_exitoso','Inicio de sesión de \"marilin\".','127.0.0.1','2026-08-21 22:43:08.918690',4),(22,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-21 22:43:56.447977',3),(23,'','solicitar_cita','Registró al paciente Rafael Ordoñez (DPI 3338889977777) y solicitó cita de Rayos X abdomen AP para 2026-08-22 07:45:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-21 22:44:39.557278',3),(24,'marilin','login_exitoso','Inicio de sesión de \"marilin\".','127.0.0.1','2026-08-21 22:44:57.684052',4),(25,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-21 22:45:31.246945',7),(26,'','confirmar_cita','Confirmó la cita de Rafael Ordoñez (3338889977777) para el 2026-08-22 a las 07:45 (cita #25).','127.0.0.1','2026-08-21 22:45:45.405972',7),(27,'','rechazar_cita','Rechazó la solicitud de cita de Rodrigro Perez (2545340000000) (cita #20). Motivo: —','127.0.0.1','2026-08-21 22:46:05.745506',7),(28,'','confirmar_cita','Confirmó la cita de Vitor Perez (8855205499799) para el 2026-08-22 a las 07:00 (cita #23).','127.0.0.1','2026-08-21 22:46:11.431126',7),(29,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".','127.0.0.1','2026-08-21 23:20:16.767933',NULL),(30,'','enviar_reporte_diario','Envió el reporte diario de COEX del 2026-08-21 al administrador.','127.0.0.1','2026-08-21 23:23:59.633491',NULL),(31,'adminfin_prueba','login_exitoso','Inicio de sesión de \"adminfin_prueba\".','127.0.0.1','2026-08-21 23:28:58.503581',NULL),(32,'adminfin_prueba','login_exitoso','Inicio de sesión de \"adminfin_prueba\".',NULL,'2026-08-21 23:29:59.722211',NULL),(33,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".',NULL,'2026-08-21 23:30:00.630055',NULL),(34,'adminfin_prueba','login_exitoso','Inicio de sesión de \"adminfin_prueba\".',NULL,'2026-08-21 23:30:28.380452',NULL),(35,'adminfin_prueba','login_exitoso','Inicio de sesión de \"adminfin_prueba\".',NULL,'2026-08-21 23:31:01.436083',NULL),(36,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".',NULL,'2026-08-21 23:31:02.503696',NULL),(37,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".',NULL,'2026-08-21 23:31:18.789502',NULL),(38,'Mayh','login_fallido','Intento de inicio de sesión fallido para \"Mayh\".','127.0.0.1','2026-08-21 23:37:08.289498',9),(39,'Mayh','login_fallido','Intento de inicio de sesión fallido para \"Mayh\".','127.0.0.1','2026-08-21 23:37:55.987793',9),(40,'Adriana','login_exitoso','Inicio de sesión de \"Adriana\".','127.0.0.1','2026-08-21 23:44:26.557636',17),(41,'Daniel','login_fallido','Intento de inicio de sesión fallido para \"Daniel\".','127.0.0.1','2026-08-21 23:46:41.019760',NULL),(42,'Daniel','login_fallido','Intento de inicio de sesión fallido para \"Daniel\".','127.0.0.1','2026-08-21 23:46:54.823692',NULL),(43,'Daniel','login_fallido','Intento de inicio de sesión fallido para \"Daniel\".','127.0.0.1','2026-08-21 23:47:11.988805',NULL),(44,'Adriana','login_exitoso','Inicio de sesión de \"Adriana\".','127.0.0.1','2026-08-21 23:47:23.228120',17),(45,'','crear_usuario','Creó el usuario \"Roberto\" con rol Administrador financiero.','127.0.0.1','2026-08-21 23:49:35.330284',17),(46,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".','127.0.0.1','2026-08-21 23:49:57.825736',18),(47,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-21 23:50:41.414224',3),(48,'','enviar_reporte_diario','Envió el reporte diario de COEX del 2026-08-21 al administrador.','127.0.0.1','2026-08-21 23:51:46.215528',3),(49,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".','127.0.0.1','2026-08-21 23:52:03.264242',18),(50,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-21 23:52:52.326578',3),(51,'','reagendar_cita','Reagendó la cita de Antony Gordon (8895000154578) para el 2026-08-22 a las 08:15 (cita #21).','127.0.0.1','2026-08-21 23:53:10.831074',3),(52,'','marcar_llegada','Marcó la llegada de Vitor Perez (8855205499799) (cita #23).','127.0.0.1','2026-08-21 23:53:19.731534',3),(53,'','marcar_llegada','Marcó la llegada de Rafael Ordoñez (3338889977777) (cita #25).','127.0.0.1','2026-08-21 23:53:21.606470',3),(54,'','marcar_llegada','Marcó la llegada de Antony Gordon (8895000154578) (cita #21).','127.0.0.1','2026-08-21 23:53:22.839400',3),(55,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".','127.0.0.1','2026-08-22 00:00:56.313321',18),(56,'adminfin_prueba','login_exitoso','Inicio de sesión de \"adminfin_prueba\".','127.0.0.1','2026-08-22 00:07:37.684252',NULL),(57,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 00:09:41.315986',3),(58,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".','127.0.0.1','2026-08-22 00:15:43.752276',18),(59,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 00:16:02.412821',3),(60,'','generar_orden','Generó la orden de trabajo para Vitor Perez (8855205499799) (cita #23).','127.0.0.1','2026-08-22 00:16:45.566434',3),(61,'','generar_orden','Generó la orden de trabajo para Rafael Ordoñez (3338889977777) (cita #25).','127.0.0.1','2026-08-22 00:16:50.879695',3),(62,'','generar_orden','Generó la orden de trabajo para Antony Gordon (8895000154578) (cita #21).','127.0.0.1','2026-08-22 00:16:56.471981',3),(63,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-22 00:17:25.936735',7),(64,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".','127.0.0.1','2026-08-22 00:17:50.649264',18),(65,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 00:18:32.406311',3),(66,'recep_prueba','login_exitoso','Inicio de sesión de \"recep_prueba\".','127.0.0.1','2026-08-22 00:24:31.152368',NULL),(67,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 13:15:58.805845',3),(68,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 13:42:39.292107',3),(69,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 13:42:48.911621',3),(70,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 13:44:46.572043',3),(71,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 14:19:44.694692',3),(72,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 14:23:02.296410',3),(73,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".',NULL,'2026-08-22 14:23:17.928408',18),(74,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".',NULL,'2026-08-22 14:23:59.836144',18),(75,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 14:27:14.232898',3),(76,'','enviar_reporte_diario','Envió el reporte diario de COEX del 2026-08-22 al administrador.','127.0.0.1','2026-08-22 14:27:14.333119',3),(77,'Roberto','login_exitoso','Inicio de sesión de \"Roberto\".',NULL,'2026-08-22 14:27:14.376203',18),(78,'admin','login_exitoso','Inicio de sesión de \"admin\".','127.0.0.1','2026-08-22 14:28:29.725725',1),(79,'elmer','login_fallido','Intento de inicio de sesión fallido para \"elmer\".','127.0.0.1','2026-08-22 14:29:41.475301',3),(80,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 14:29:46.359696',3),(81,'admin','login_exitoso','Inicio de sesión de \"admin\".',NULL,'2026-08-22 14:31:15.463206',1),(82,'admin','login_exitoso','Inicio de sesión de \"admin\".',NULL,'2026-08-22 14:31:29.559747',1),(83,'admin','login_exitoso','Inicio de sesión de \"admin\".','127.0.0.1','2026-08-22 14:31:39.705845',1),(84,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 14:33:54.850944',3),(85,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 14:34:07.123913',3),(86,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 14:34:15.134844',3),(87,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 16:43:35.892657',3),(88,'tecnico1','login_exitoso','Inicio de sesión de \"tecnico1\".','127.0.0.1','2026-08-22 16:44:53.452038',2),(89,'tecnico1','login_exitoso','Inicio de sesión de \"tecnico1\".','127.0.0.1','2026-08-22 17:04:14.867965',2),(90,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:11:15.258859',3),(91,'radiolo1','login_fallido','Intento de inicio de sesión fallido para \"radiolo1\".','127.0.0.1','2026-08-22 17:14:50.365012',NULL),(92,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-22 17:15:07.032323',7),(93,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:25:20.216124',3),(94,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:38:25.326518',3),(95,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:38:47.391078',3),(96,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:39:05.947458',3),(97,'verificacion_visual','login_exitoso','Inicio de sesión de \"verificacion_visual\".','127.0.0.1','2026-08-22 17:39:56.165678',NULL),(98,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:40:19.340727',3),(99,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:41:07.678335',3),(100,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:42:35.924543',3),(101,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:43:27.355696',3),(102,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:46:15.630456',3),(103,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 17:46:59.358160',3),(104,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 17:55:56.354466',3),(105,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 17:56:11.555043',3),(106,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:04:28.559215',3),(107,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:04:40.700714',3),(108,'','solicitar_cita','Registró al paciente Paciente Uno (DPI 1111111111111) y solicitó cita de Tórax para 2026-08-24 09:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-22 18:04:40.809606',3),(109,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-22 18:06:02.927450',7),(110,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:11:47.792048',3),(111,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:12:02.507770',3),(112,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:12:35.865810',3),(113,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 18:15:08.681982',3),(114,'','solicitar_cita','Registró al paciente Paciente Uno (DPI 1111111111111) y solicitó cita de Tórax para 2026-08-24 07:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-22 18:15:28.560638',3),(115,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-22 18:15:48.324701',7),(116,'','confirmar_cita','Confirmó la cita de Paciente Uno (1111111111111) para el 2026-08-24 a las 09:00 (cita #37).','127.0.0.1','2026-08-22 18:15:55.594051',7),(117,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 18:16:06.367125',3),(118,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:21:28.028282',3),(119,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:21:53.287987',3),(120,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:22:07.163555',3),(121,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:22:27.162046',3),(122,'tecnico1','login_exitoso','Inicio de sesión de \"tecnico1\".','127.0.0.1','2026-08-22 18:26:50.170531',2),(123,'admin','login_exitoso','Inicio de sesión de \"admin\".',NULL,'2026-08-22 18:29:38.329309',1),(124,'admin','login_exitoso','Inicio de sesión de \"admin\".',NULL,'2026-08-22 18:29:56.539939',1),(125,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:29:56.676340',3),(126,'','editar_estudio','Editó el estudio \"Tórax\" (precio: 112.00, duración: 99 min).','127.0.0.1','2026-08-22 18:29:56.730625',1),(127,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 18:31:15.038054',3),(128,'','solicitar_cita','Registró al paciente Paciente Dos (DPI 2222222222222) y solicitó cita de Rayos X pie para 2026-08-25 07:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-22 18:31:50.955345',3),(129,'radiologo1','login_fallido','Intento de inicio de sesión fallido para \"radiologo1\".','127.0.0.1','2026-08-22 18:32:26.903262',7),(130,'radiologo1','login_exitoso','Inicio de sesión de \"radiologo1\".','127.0.0.1','2026-08-22 18:32:35.633511',7),(131,'','confirmar_cita','Confirmó la cita de Paciente Dos (2222222222222) para el 2026-08-25 a las 13:00 (cita #42).','127.0.0.1','2026-08-22 18:32:45.727101',7),(132,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 18:32:58.654783',3),(133,'','solicitar_cita','Registró al paciente Paciente Dos (DPI 2222222222222) y solicitó cita de TAC de cráneo para 2026-08-25 13:15:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-22 18:33:50.893313',3),(134,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:42:25.360759',3),(135,'','solicitar_cita','[EMERGENCIA] Registró al paciente Paciente Dos (DPI 2222222222222) y solicitó cita de Tórax para 2026-08-31 08:00:00 (coex), asignada a radiologo1. Se agendó encima de otra cita ya existente por tratarse de una emergencia.','127.0.0.1','2026-08-22 18:42:25.535286',3),(136,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 18:42:43.784266',3),(137,'','solicitar_cita','[EMERGENCIA] Registró al paciente Paciente Dos (DPI 2222222222222) y solicitó cita de Tórax para 2026-08-31 08:00:00 (coex), asignada a radiologo1. Se agendó encima de otra cita ya existente por tratarse de una emergencia.','127.0.0.1','2026-08-22 18:42:43.880682',3),(138,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".','127.0.0.1','2026-08-22 19:40:00.360259',3),(139,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 19:45:45.398889',3),(140,'','solicitar_cita','Registró al paciente Prueba Notificacion (DPI 9999999999999) y solicitó cita de Tórax para 2026-09-01 11:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-22 19:45:45.914233',3),(141,'','solicitar_cita','Registró al paciente Prueba Notificacion (DPI 9999999999999) y solicitó cita de Tórax para 2026-09-02 11:00:00 (coex), asignada a radiologo1.','127.0.0.1','2026-08-22 19:45:46.116789',3),(142,'Elmer','login_exitoso','Inicio de sesión de \"Elmer\".',NULL,'2026-08-22 19:51:04.548560',3);
/*!40000 ALTER TABLE `bitacora` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `citas`
--

DROP TABLE IF EXISTS `citas`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `citas` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `convenio` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `estado` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `fecha` date NOT NULL,
  `hora` time(6) NOT NULL,
  `notas` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `creada_en` datetime(6) NOT NULL,
  `creada_por_id` bigint NOT NULL,
  `paciente_id` bigint NOT NULL,
  `tipo_estudio_id` bigint NOT NULL,
  `hora_llegada` datetime(6) DEFAULT NULL,
  `fecha_sugerida` date DEFAULT NULL,
  `hora_sugerida` time(6) DEFAULT NULL,
  `motivo_rechazo` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `revisada_en` datetime(6) DEFAULT NULL,
  `revisada_por_id` bigint DEFAULT NULL,
  `radiologo_id` bigint DEFAULT NULL,
  `medico_referente` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `es_emergencia_forzada` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `citas_creada_por_id_e68819fa_fk_usuarios_id` (`creada_por_id`),
  KEY `citas_paciente_id_79b6833d_fk_pacientes_id` (`paciente_id`),
  KEY `citas_tipo_estudio_id_10b1026b_fk_tipos_estudio_id` (`tipo_estudio_id`),
  KEY `citas_revisada_por_id_ebf518ad_fk_usuarios_id` (`revisada_por_id`),
  KEY `citas_radiologo_id_8c5156b2_fk_usuarios_id` (`radiologo_id`),
  CONSTRAINT `citas_creada_por_id_e68819fa_fk_usuarios_id` FOREIGN KEY (`creada_por_id`) REFERENCES `usuarios` (`id`),
  CONSTRAINT `citas_paciente_id_79b6833d_fk_pacientes_id` FOREIGN KEY (`paciente_id`) REFERENCES `pacientes` (`id`),
  CONSTRAINT `citas_radiologo_id_8c5156b2_fk_usuarios_id` FOREIGN KEY (`radiologo_id`) REFERENCES `usuarios` (`id`),
  CONSTRAINT `citas_revisada_por_id_ebf518ad_fk_usuarios_id` FOREIGN KEY (`revisada_por_id`) REFERENCES `usuarios` (`id`),
  CONSTRAINT `citas_tipo_estudio_id_10b1026b_fk_tipos_estudio_id` FOREIGN KEY (`tipo_estudio_id`) REFERENCES `tipos_estudio` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=54 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `citas`
--

LOCK TABLES `citas` WRITE;
/*!40000 ALTER TABLE `citas` DISABLE KEYS */;
INSERT INTO `citas` VALUES (1,'coex','ausente','2026-08-03','09:30:00.000000','Referida por IGSS, traer orden impresa.','2026-07-28 04:26:04.362698',3,1,3,NULL,NULL,NULL,'',NULL,NULL,NULL,'',0),(2,'coex','procesada','2026-07-27','13:00:00.000000','','2026-07-28 04:34:24.863014',3,2,1,NULL,NULL,NULL,'',NULL,NULL,NULL,'',0),(3,'coex','ausente','2026-07-28','07:00:00.000000','','2026-07-28 04:34:49.331282',3,3,1,NULL,NULL,NULL,'',NULL,NULL,NULL,'',0),(4,'coex','ausente','2026-07-28','10:00:00.000000','','2026-07-28 04:35:13.527580',3,4,1,'2026-07-28 05:16:02.935937',NULL,NULL,'',NULL,NULL,NULL,'',0),(5,'coex','procesada','2026-07-27','07:00:00.000000','','2026-07-28 04:58:49.244949',2,5,2,'2026-07-28 04:59:11.329133',NULL,NULL,'',NULL,NULL,NULL,'',0),(6,'coex','en_proceso','2026-07-27','08:00:00.000000','','2026-07-28 05:25:17.049089',3,6,1,'2026-07-28 05:25:17.053126',NULL,NULL,'',NULL,NULL,NULL,'',0),(7,'coex','en_proceso','2026-07-31','07:00:00.000000','el paciente paqueño','2026-07-29 18:15:34.752863',3,7,1,'2026-07-30 22:59:29.192133',NULL,NULL,'',NULL,NULL,NULL,'',0),(9,'privado','procesada','2026-07-27','08:00:00.000000','','2026-07-31 02:59:03.474291',3,2,1,'2026-07-27 13:00:00.000000',NULL,NULL,'',NULL,NULL,NULL,'',0),(10,'privado','ausente','2026-07-28','09:00:00.000000','','2026-07-31 02:59:03.474291',3,3,2,NULL,NULL,NULL,'',NULL,NULL,NULL,'',0),(11,'privado','en_proceso','2026-07-29','10:00:00.000000','','2026-07-31 02:59:03.485503',3,4,3,'2026-07-29 15:00:00.000000',NULL,NULL,'',NULL,NULL,NULL,'',0),(12,'privado','ausente','2026-07-30','11:00:00.000000','','2026-07-31 02:59:03.494541',3,5,4,NULL,NULL,NULL,'',NULL,NULL,NULL,'',0),(13,'privado','en_proceso','2026-07-30','14:00:00.000000','','2026-07-31 02:59:03.499209',3,6,1,'2026-07-30 19:00:00.000000',NULL,NULL,'',NULL,NULL,NULL,'',0),(14,'privado','en_proceso','2026-07-31','09:00:00.000000','','2026-07-31 02:59:03.506118',3,7,2,'2026-07-31 14:00:00.000000',NULL,NULL,'',NULL,NULL,NULL,'',0),(15,'privado','ausente','2026-08-01','10:00:00.000000','','2026-07-31 02:59:03.513690',3,1,1,NULL,NULL,NULL,'',NULL,NULL,NULL,'',0),(20,'coex','rechazada','2026-08-21','09:00:00.000000','sdf','2026-08-20 21:51:05.163177',3,9,9,NULL,'2026-08-21','09:00:00.000000','','2026-08-21 22:46:05.731315',7,7,'',0),(21,'coex','en_proceso','2026-08-22','08:15:00.000000','asdfsdf','2026-08-20 21:53:05.154645',3,10,9,'2026-08-21 23:53:22.835481','2026-08-21','07:00:00.000000','','2026-08-20 21:54:20.103090',7,7,'',0),(23,'coex','en_proceso','2026-08-22','07:00:00.000000','asdfsf','2026-08-21 22:14:30.405593',3,12,14,'2026-08-21 23:53:19.725296','2026-08-22','07:00:00.000000','','2026-08-21 22:46:11.416281',7,7,'',0),(25,'coex','en_proceso','2026-08-22','07:45:00.000000','asdf','2026-08-21 22:44:39.548525',3,14,13,'2026-08-21 23:53:21.602595','2026-08-22','07:45:00.000000','','2026-08-21 22:45:45.391708',7,7,'',0),(27,'coex','agendada','2026-08-22','09:00:00.000000','','2026-08-22 17:49:47.182001',3,16,6,NULL,NULL,NULL,'',NULL,NULL,7,'',0),(28,'privado','pendiente','2026-08-22','10:00:00.000000','Paciente refiere dolor de rodilla tras caida, solicita cita lo antes posible.','2026-08-22 17:49:47.195450',3,17,7,NULL,'2026-08-22','10:00:00.000000','',NULL,NULL,NULL,'',0),(29,'coex','en_proceso','2026-08-22','11:00:00.000000','','2026-08-22 17:49:47.207675',3,18,8,NULL,NULL,NULL,'',NULL,NULL,7,'',0),(30,'emergencia_igss','en_proceso','2026-08-22','08:30:00.000000','','2026-08-22 17:49:47.224001',3,19,9,NULL,NULL,NULL,'',NULL,NULL,7,'',0),(31,'privado','procesada','2026-08-21','14:00:00.000000','','2026-08-22 17:49:47.249645',3,20,10,NULL,NULL,NULL,'',NULL,NULL,7,'',0),(32,'coex','ausente','2026-08-21','15:00:00.000000','','2026-08-22 17:49:47.279944',3,21,13,NULL,NULL,NULL,'',NULL,NULL,7,'',0),(33,'privado','rechazada','2026-08-22','16:00:00.000000','','2026-08-22 17:49:47.292646',3,22,12,NULL,NULL,NULL,'El paciente no cuenta con orden medica ni referencia para el estudio solicitado.','2026-08-22 17:49:47.291654',1,NULL,'',0),(34,'emergencia_igss','pendiente','2026-08-22','09:30:00.000000','Tos persistente y fiebre, referida por medico de turno.','2026-08-22 17:49:47.340056',3,24,6,NULL,'2026-08-22','09:30:00.000000','',NULL,NULL,NULL,'',0),(35,'privado','procesada','2026-08-20','13:00:00.000000','','2026-08-22 17:49:47.349486',3,25,12,NULL,NULL,NULL,'',NULL,NULL,7,'',0),(37,'coex','agendada','2026-08-24','09:00:00.000000','prueba','2026-08-22 18:15:28.550642',3,2,6,NULL,'2026-08-24','07:00:00.000000','','2026-08-22 18:15:55.576353',7,7,'',0),(39,'coex','pendiente','2026-08-24','07:00:00.000000','','2026-08-22 18:21:53.311657',3,2,6,NULL,'2026-08-24','07:00:00.000000','',NULL,NULL,7,'',0),(40,'coex','pendiente','2026-08-24','07:00:00.000000','','2026-08-22 18:22:07.186944',3,2,6,NULL,'2026-08-24','07:00:00.000000','',NULL,NULL,7,'',0),(42,'coex','agendada','2026-08-25','13:00:00.000000','prueba','2026-08-22 18:31:50.944502',3,3,9,NULL,'2026-08-25','07:00:00.000000','','2026-08-22 18:32:45.710202',7,7,'',0),(43,'coex','pendiente','2026-08-25','13:15:00.000000','asa','2026-08-22 18:33:50.885200',3,3,14,NULL,'2026-08-25','13:15:00.000000','',NULL,NULL,7,'',0);
/*!40000 ALTER TABLE `citas` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_migrations`
--

DROP TABLE IF EXISTS `django_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_migrations` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `app` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=53 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_migrations`
--

LOCK TABLES `django_migrations` WRITE;
/*!40000 ALTER TABLE `django_migrations` DISABLE KEYS */;
INSERT INTO `django_migrations` VALUES (1,'sessions','0001_initial','2026-07-28 03:04:52.986069'),(2,'contenttypes','0001_initial','2026-07-28 03:04:53.039805'),(3,'contenttypes','0002_remove_content_type_name','2026-07-28 03:04:53.175223'),(4,'auth','0001_initial','2026-07-28 03:04:53.564959'),(5,'auth','0002_alter_permission_name_max_length','2026-07-28 03:04:53.710830'),(6,'auth','0003_alter_user_email_max_length','2026-07-28 03:04:53.715015'),(7,'auth','0004_alter_user_username_opts','2026-07-28 03:04:53.725140'),(8,'auth','0005_alter_user_last_login_null','2026-07-28 03:04:53.741102'),(9,'auth','0006_require_contenttypes_0002','2026-07-28 03:04:53.745045'),(10,'auth','0007_alter_validators_add_error_messages','2026-07-28 03:04:53.761296'),(11,'auth','0008_alter_user_username_max_length','2026-07-28 03:04:53.765039'),(12,'auth','0009_alter_user_last_name_max_length','2026-07-28 03:04:53.775198'),(13,'auth','0010_alter_group_name_max_length','2026-07-28 03:04:53.812149'),(14,'auth','0011_update_proxy_permissions','2026-07-28 03:04:53.826594'),(15,'auth','0012_alter_user_first_name_max_length','2026-07-28 03:04:53.838412'),(16,'accounts','0001_initial','2026-07-28 03:04:54.316307'),(17,'admin','0001_initial','2026-07-28 03:04:54.534938'),(18,'admin','0002_logentry_remove_auto_add','2026-07-28 03:04:54.544724'),(19,'admin','0003_logentry_add_action_flag_choices','2026-07-28 03:04:54.555409'),(20,'accounts','0002_traducir_tablas_django','2026-07-28 03:04:54.715116'),(21,'accounts','0003_usuario_rol','2026-07-28 03:29:54.883576'),(22,'pacientes','0001_initial','2026-07-28 04:22:20.866155'),(23,'pacientes','0002_seed_tipos_estudio','2026-07-28 04:22:20.889785'),(24,'pacientes','0003_alter_cita_estado','2026-07-28 04:50:40.404636'),(25,'pacientes','0004_cita_hora_llegada','2026-07-28 04:57:19.071432'),(26,'pacientes','0005_paciente_sexo_alter_cita_estado_ordentrabajo','2026-07-28 05:21:14.265555'),(27,'accounts','0004_usuario_porcentaje_coex_and_more','2026-08-19 23:54:40.385666'),(28,'accounts','0005_bitacora','2026-08-19 23:54:40.466405'),(29,'accounts','0006_alter_bitacora_accion','2026-08-19 23:54:40.475404'),(30,'accounts','0007_alter_bitacora_accion','2026-08-19 23:54:40.483412'),(31,'pacientes','0006_ordentrabajo_informe_archivo_and_more','2026-08-19 23:54:40.690890'),(32,'pacientes','0007_cita_fecha_sugerida_cita_hora_sugerida_and_more','2026-08-19 23:54:40.842036'),(33,'pacientes','0008_tipoestudio_precio','2026-08-19 23:54:40.866651'),(34,'pacientes','0009_tipoestudio_activo','2026-08-19 23:54:40.886873'),(35,'pacientes','0010_desactivar_estudios_provisionales','2026-08-19 23:54:40.902059'),(36,'pacientes','0011_cita_radiologo','2026-08-19 23:54:40.968559'),(37,'pacientes','0012_asignar_radiologo_pendientes','2026-08-19 23:54:40.983138'),(38,'pacientes','0013_dailysequence_ticket','2026-08-19 23:54:41.121169'),(39,'pacientes','0014_ticket_cita','2026-08-19 23:54:41.180022'),(40,'pacientes','0015_notificacion','2026-08-19 23:54:41.456709'),(41,'pacientes','0016_alter_notificacion_tipo','2026-08-19 23:54:41.470216'),(42,'pacientes','0017_paciente_carnet_igss','2026-08-19 23:54:41.546139'),(43,'pacientes','0018_tipoestudio_radiologos','2026-08-19 23:54:41.667492'),(44,'pacientes','0019_asignar_radiologos_existentes','2026-08-19 23:54:41.682486'),(45,'pacientes','0020_alter_notificacion_tipo_and_more','2026-08-19 23:54:41.771194'),(46,'pacientes','0021_tipoestudio_duracion_minutos','2026-08-20 21:22:38.496269'),(47,'accounts','0008_alter_usuario_rol','2026-08-21 23:17:06.365531'),(48,'accounts','0009_alter_bitacora_accion','2026-08-21 23:17:06.376373'),(49,'pacientes','0022_cita_medico_referente_reportediario','2026-08-21 23:17:06.566528'),(50,'pacientes','0023_alter_notificacion_tipo','2026-08-22 14:26:54.240680'),(51,'accounts','0010_alter_bitacora_accion','2026-08-22 18:27:41.694964'),(52,'pacientes','0024_cita_es_emergencia_forzada','2026-08-22 18:41:40.057906');
/*!40000 ALTER TABLE `django_migrations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `grupos`
--

DROP TABLE IF EXISTS `grupos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `grupos` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `grupos`
--

LOCK TABLES `grupos` WRITE;
/*!40000 ALTER TABLE `grupos` DISABLE KEYS */;
/*!40000 ALTER TABLE `grupos` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `grupos_permisos`
--

DROP TABLE IF EXISTS `grupos_permisos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `grupos_permisos` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `group_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `permisos` (`id`),
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `grupos` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `grupos_permisos`
--

LOCK TABLES `grupos_permisos` WRITE;
/*!40000 ALTER TABLE `grupos_permisos` DISABLE KEYS */;
/*!40000 ALTER TABLE `grupos_permisos` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `imagenes_estudio`
--

DROP TABLE IF EXISTS `imagenes_estudio`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `imagenes_estudio` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `archivo` varchar(100) NOT NULL,
  `subida_en` datetime(6) NOT NULL,
  `orden_id` bigint NOT NULL,
  `subida_por_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `imagenes_estudio_orden_id_c1ab4c79_fk_ordenes_trabajo_id` (`orden_id`),
  KEY `imagenes_estudio_subida_por_id_4006a4ee_fk_usuarios_id` (`subida_por_id`),
  CONSTRAINT `imagenes_estudio_orden_id_c1ab4c79_fk_ordenes_trabajo_id` FOREIGN KEY (`orden_id`) REFERENCES `ordenes_trabajo` (`id`),
  CONSTRAINT `imagenes_estudio_subida_por_id_4006a4ee_fk_usuarios_id` FOREIGN KEY (`subida_por_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `imagenes_estudio`
--

LOCK TABLES `imagenes_estudio` WRITE;
/*!40000 ALTER TABLE `imagenes_estudio` DISABLE KEYS */;
INSERT INTO `imagenes_estudio` VALUES (1,'imagenes_estudio/2026/08/pie_ap.png','2026-08-22 17:49:47.238094',10,2),(2,'imagenes_estudio/2026/08/columna_1.png','2026-08-22 17:49:47.262107',11,2),(3,'imagenes_estudio/2026/08/craneo_1.png','2026-08-22 17:49:47.362189',12,2);
/*!40000 ALTER TABLE `imagenes_estudio` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `notificaciones`
--

DROP TABLE IF EXISTS `notificaciones`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notificaciones` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `tipo` varchar(30) NOT NULL,
  `mensaje` varchar(255) NOT NULL,
  `url` varchar(255) NOT NULL,
  `leida` tinyint(1) NOT NULL,
  `creada_en` datetime(6) NOT NULL,
  `cita_id` bigint DEFAULT NULL,
  `destinatario_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `notificaciones_cita_id_80bb9ddc_fk_citas_id` (`cita_id`),
  KEY `notificaciones_destinatario_id_b4c41ead_fk_usuarios_id` (`destinatario_id`),
  CONSTRAINT `notificaciones_cita_id_80bb9ddc_fk_citas_id` FOREIGN KEY (`cita_id`) REFERENCES `citas` (`id`),
  CONSTRAINT `notificaciones_destinatario_id_b4c41ead_fk_usuarios_id` FOREIGN KEY (`destinatario_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=61 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `notificaciones`
--

LOCK TABLES `notificaciones` WRITE;
/*!40000 ALTER TABLE `notificaciones` DISABLE KEYS */;
INSERT INTO `notificaciones` VALUES (2,'cita_asignada','Nueva cita asignada: Rayos X pie para Rodrigro Perez el 2026-08-21 a las 09:00:00.','/citas/solicitudes/',0,'2026-08-20 21:51:05.166188',20,7),(3,'cita_asignada','Nueva cita asignada: Rayos X pie para Antony Gordon el 2026-08-21 a las 07:00:00.','/citas/solicitudes/',0,'2026-08-20 21:53:05.158756',21,7),(4,'cita_confirmada','Cita confirmada: Rayos X pie de Antony Gordon el 2026-08-21 a las 07:00:00.','/citas/calendario/coex/',1,'2026-08-20 21:54:20.111753',21,3),(6,'cita_asignada','Nueva cita asignada: TAC de cráneo para Vitor Perez el 2026-08-22 a las 07:00:00.','/citas/solicitudes/',0,'2026-08-21 22:14:30.408613',23,7),(7,'cita_asignada','Nueva cita asignada: Rayos X abdomen AP para Rafael Ordoñez el 2026-08-22 a las 07:45:00.','/citas/solicitudes/',0,'2026-08-21 22:44:39.553532',25,7),(8,'cita_confirmada','Cita confirmada: Rayos X abdomen AP de Rafael Ordoñez el 2026-08-22 a las 07:45:00.','/citas/calendario/coex/',1,'2026-08-21 22:45:45.401498',25,3),(9,'cita_rechazada','Cita rechazada: Rayos X pie de Rodrigro Perez. Motivo: —','/citas/calendario/coex/',1,'2026-08-21 22:46:05.743509',20,3),(10,'cita_confirmada','Cita confirmada: TAC de cráneo de Vitor Perez el 2026-08-22 a las 07:00:00.','/citas/calendario/coex/',1,'2026-08-21 22:46:11.427614',23,3),(11,'orden_pendiente','Nueva orden de trabajo: TAC de cráneo para Vitor Perez.','/ordenes/pendientes/',0,'2026-08-22 00:16:45.563435',23,2),(12,'orden_pendiente','Nueva orden de trabajo: TAC de cráneo para Vitor Perez.','/ordenes/pendientes/',0,'2026-08-22 00:16:45.563435',23,4),(13,'orden_pendiente','Nueva orden de trabajo: TAC de cráneo para Vitor Perez.','/ordenes/pendientes/',0,'2026-08-22 00:16:45.563435',23,5),(14,'orden_pendiente','Nueva orden de trabajo: Rayos X abdomen AP para Rafael Ordoñez.','/ordenes/pendientes/',0,'2026-08-22 00:16:50.875484',25,2),(15,'orden_pendiente','Nueva orden de trabajo: Rayos X abdomen AP para Rafael Ordoñez.','/ordenes/pendientes/',0,'2026-08-22 00:16:50.875484',25,4),(16,'orden_pendiente','Nueva orden de trabajo: Rayos X abdomen AP para Rafael Ordoñez.','/ordenes/pendientes/',0,'2026-08-22 00:16:50.875484',25,5),(17,'orden_pendiente','Nueva orden de trabajo: Rayos X pie para Antony Gordon.','/ordenes/pendientes/',0,'2026-08-22 00:16:56.469280',21,2),(18,'orden_pendiente','Nueva orden de trabajo: Rayos X pie para Antony Gordon.','/ordenes/pendientes/',0,'2026-08-22 00:16:56.469280',21,4),(19,'orden_pendiente','Nueva orden de trabajo: Rayos X pie para Antony Gordon.','/ordenes/pendientes/',0,'2026-08-22 00:16:56.469280',21,5),(20,'reporte_enviado','Nuevo reporte diario enviado: COEX del 2026-08-22, por Elmer Adrián Melendrez Catalan.','/reportes/coex/2026-08-22/',0,'2026-08-22 14:27:14.342796',NULL,18),(22,'cita_asignada','Nueva cita asignada: Tórax para Paciente Uno el 2026-08-24 a las 07:00:00.','/citas/solicitudes/',0,'2026-08-22 18:15:28.555628',37,7),(23,'cita_confirmada','Cita confirmada: Tórax de Paciente Uno el 2026-08-24 a las 09:00:00.','/citas/calendario/coex/',1,'2026-08-22 18:15:55.590262',37,3),(24,'cita_asignada','Nueva cita asignada: Rayos X pie para Paciente Dos el 2026-08-25 a las 07:00:00.','/citas/solicitudes/',0,'2026-08-22 18:31:50.950884',42,7),(25,'cita_confirmada','Cita confirmada: Rayos X pie de Paciente Dos el 2026-08-25 a las 13:00:00.','/citas/calendario/coex/',1,'2026-08-22 18:32:45.724117',42,3),(26,'cita_asignada','Nueva cita asignada: TAC de cráneo para Paciente Dos el 2026-08-25 a las 13:15:00.','/citas/solicitudes/',0,'2026-08-22 18:33:50.889605',43,7),(33,'datos_paciente_pendientes','Ana Gomez (DPI 7777777777777) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/6/',0,'2026-08-22 19:46:06.554517',NULL,3),(34,'datos_paciente_pendientes','Ana Gomez (DPI 7777777777777) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/6/',0,'2026-08-22 19:46:06.554517',NULL,22),(35,'datos_paciente_pendientes','Antony Gordon (DPI 8895000154578) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/10/',0,'2026-08-22 19:46:06.567672',NULL,3),(36,'datos_paciente_pendientes','Antony Gordon (DPI 8895000154578) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/10/',0,'2026-08-22 19:46:06.567672',NULL,22),(37,'datos_paciente_pendientes','Carlos Ramirez (DPI 5555555555555) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/5/',0,'2026-08-22 19:46:06.579499',NULL,3),(38,'datos_paciente_pendientes','Carlos Ramirez (DPI 5555555555555) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/5/',0,'2026-08-22 19:46:06.580059',NULL,22),(39,'datos_paciente_pendientes','Carlos Ramirez (DPI 9000000000003) tiene datos pendientes: Sexo, Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/17/',0,'2026-08-22 19:46:06.592509',NULL,3),(40,'datos_paciente_pendientes','Carlos Ramirez (DPI 9000000000003) tiene datos pendientes: Sexo, Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/17/',0,'2026-08-22 19:46:06.592509',NULL,22),(41,'datos_paciente_pendientes','Jorge Morales (DPI 9000000000007) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/21/',0,'2026-08-22 19:46:06.603706',NULL,3),(42,'datos_paciente_pendientes','Jorge Morales (DPI 9000000000007) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/21/',0,'2026-08-22 19:46:06.603706',NULL,22),(43,'datos_paciente_pendientes','Paciente Dos (DPI 2222222222222) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/3/',0,'2026-08-22 19:46:06.617434',NULL,3),(44,'datos_paciente_pendientes','Paciente Dos (DPI 2222222222222) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/3/',0,'2026-08-22 19:46:06.617434',NULL,22),(45,'datos_paciente_pendientes','Paciente Tres (DPI 3333333333333) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/4/',0,'2026-08-22 19:46:06.631180',NULL,3),(46,'datos_paciente_pendientes','Paciente Tres (DPI 3333333333333) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/4/',0,'2026-08-22 19:46:06.631180',NULL,22),(47,'datos_paciente_pendientes','Paciente Uno (DPI 1111111111111) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/2/',0,'2026-08-22 19:46:06.646038',NULL,3),(48,'datos_paciente_pendientes','Paciente Uno (DPI 1111111111111) tiene datos pendientes: Teléfono.','/pacientes/completar-datos/2/',0,'2026-08-22 19:46:06.646038',NULL,22),(49,'datos_paciente_pendientes','Pedro Ramirez (DPI 9000000000005) tiene datos pendientes: Fecha de nacimiento.','/pacientes/completar-datos/19/',0,'2026-08-22 19:46:06.657598',NULL,3),(50,'datos_paciente_pendientes','Pedro Ramirez (DPI 9000000000005) tiene datos pendientes: Fecha de nacimiento.','/pacientes/completar-datos/19/',0,'2026-08-22 19:46:06.657598',NULL,22),(51,'datos_paciente_pendientes','Rafael Ordoñez (DPI 3338889977777) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/14/',0,'2026-08-22 19:46:06.668206',NULL,3),(52,'datos_paciente_pendientes','Rafael Ordoñez (DPI 3338889977777) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/14/',0,'2026-08-22 19:46:06.668206',NULL,22),(53,'datos_paciente_pendientes','Rodrigro Perez (DPI 2545340000000) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/9/',0,'2026-08-22 19:46:06.681701',NULL,3),(54,'datos_paciente_pendientes','Rodrigro Perez (DPI 2545340000000) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/9/',0,'2026-08-22 19:46:06.681701',NULL,22),(55,'datos_paciente_pendientes','Sofia Guzman (DPI 9000000000008) tiene datos pendientes: Sexo, Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/22/',0,'2026-08-22 19:46:06.695092',NULL,3),(56,'datos_paciente_pendientes','Sofia Guzman (DPI 9000000000008) tiene datos pendientes: Sexo, Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/22/',0,'2026-08-22 19:46:06.695092',NULL,22),(57,'datos_paciente_pendientes','Valentina Castillo (DPI 9000000000010) tiene datos pendientes: Sexo.','/pacientes/completar-datos/24/',0,'2026-08-22 19:46:06.706930',NULL,3),(58,'datos_paciente_pendientes','Valentina Castillo (DPI 9000000000010) tiene datos pendientes: Sexo.','/pacientes/completar-datos/24/',0,'2026-08-22 19:46:06.706930',NULL,22),(59,'datos_paciente_pendientes','Vitor Perez (DPI 8855205499799) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/12/',0,'2026-08-22 19:46:06.717865',NULL,3),(60,'datos_paciente_pendientes','Vitor Perez (DPI 8855205499799) tiene datos pendientes: Fecha de nacimiento, Teléfono.','/pacientes/completar-datos/12/',0,'2026-08-22 19:46:06.717865',NULL,22);
/*!40000 ALTER TABLE `notificaciones` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ordenes_trabajo`
--

DROP TABLE IF EXISTS `ordenes_trabajo`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ordenes_trabajo` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `motivo` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `creada_en` datetime(6) NOT NULL,
  `cita_id` bigint NOT NULL,
  `creada_por_id` bigint NOT NULL,
  `informe_archivo` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `informe_creado_en` datetime(6) DEFAULT NULL,
  `informe_creado_por_id` bigint DEFAULT NULL,
  `informe_texto` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `cita_id` (`cita_id`),
  KEY `ordenes_trabajo_creada_por_id_c12af009_fk_usuarios_id` (`creada_por_id`),
  KEY `ordenes_trabajo_informe_creado_por_id_cbdaaf5d_fk_usuarios_id` (`informe_creado_por_id`),
  CONSTRAINT `ordenes_trabajo_cita_id_aa413d53_fk_citas_id` FOREIGN KEY (`cita_id`) REFERENCES `citas` (`id`),
  CONSTRAINT `ordenes_trabajo_creada_por_id_c12af009_fk_usuarios_id` FOREIGN KEY (`creada_por_id`) REFERENCES `usuarios` (`id`),
  CONSTRAINT `ordenes_trabajo_informe_creado_por_id_cbdaaf5d_fk_usuarios_id` FOREIGN KEY (`informe_creado_por_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ordenes_trabajo`
--

LOCK TABLES `ordenes_trabajo` WRITE;
/*!40000 ALTER TABLE `ordenes_trabajo` DISABLE KEYS */;
INSERT INTO `ordenes_trabajo` VALUES (1,'Paciente de 38 años, femenino, presenta lesiones graves en el brazo izquierdo tras caída.','2026-07-28 05:25:51.805024',6,3,NULL,NULL,NULL,''),(2,'hjhjh','2026-07-30 23:00:15.875706',7,3,NULL,NULL,NULL,''),(3,'Estudio de prueba: Tomografía','2026-07-31 02:59:03.487829',11,3,NULL,NULL,NULL,''),(4,'Estudio de prueba: Rayos X','2026-07-31 02:59:03.503450',13,3,NULL,NULL,NULL,''),(5,'Estudio de prueba: Ultrasonido','2026-07-31 02:59:03.510455',14,3,NULL,NULL,NULL,''),(6,'asdfs','2026-08-22 00:16:45.549543',23,3,'',NULL,NULL,''),(7,'hdfgdf','2026-08-22 00:16:50.868201',25,3,'',NULL,NULL,''),(8,'sgsfsfs','2026-08-22 00:16:56.457481',21,3,'',NULL,NULL,''),(9,'Dolor abdominal recurrente, descartar patologia tiroidea.','2026-08-22 17:49:47.212404',29,3,'',NULL,NULL,''),(10,'Trauma en pie derecho tras accidente.','2026-08-22 17:49:47.229794',30,3,'',NULL,NULL,''),(11,'Dolor lumbar cronico.','2026-08-22 17:49:47.254399',31,3,'','2026-08-22 17:49:47.266763',7,'Rectificacion de la lordosis lumbar fisiologica. No se observan signos de fractura ni listesis. Espacios intervertebrales conservados.'),(12,'Cefalea intensa de una semana de evolucion.','2026-08-22 17:49:47.355937',35,3,'informes/2026/08/informe_test0010.pdf','2026-08-22 17:49:47.366203',7,'');
/*!40000 ALTER TABLE `ordenes_trabajo` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `pacientes`
--

DROP TABLE IF EXISTS `pacientes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `pacientes` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `dpi` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `nombre` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `apellido` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `telefono` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `fecha_nacimiento` date DEFAULT NULL,
  `sexo` varchar(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `carnet_igss` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `dpi` (`dpi`),
  UNIQUE KEY `carnet_igss` (`carnet_igss`)
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `pacientes`
--

LOCK TABLES `pacientes` WRITE;
/*!40000 ALTER TABLE `pacientes` DISABLE KEYS */;
INSERT INTO `pacientes` VALUES (1,'1234567890101','Maria','Lopez','50212345678','1990-05-14','M',NULL),(2,'1111111111111','Paciente','Uno','','1990-01-01','M','1111111111111111111'),(3,'2222222222222','Paciente','Dos','','1990-01-01','M','2222222222222222222'),(4,'3333333333333','Paciente','Tres','','1990-01-01','M',NULL),(5,'5555555555555','Carlos','Ramirez','','1985-03-01','M',NULL),(6,'7777777777777','Ana','Gomez','','1988-06-15','F',NULL),(7,'9000000000001','pueba','jahajha','1881','2026-07-07','M',NULL),(9,'2545340000000','Rodrigro','Perez','',NULL,'M','84512033002522012268'),(10,'8895000154578','Antony','Gordon','',NULL,'M','78721545120215451202'),(12,'8855205499799','Vitor','Perez','',NULL,'M','33335555555555555555'),(14,'3338889977777','Rafael','Ordoñez','',NULL,'M','22223330000000000000'),(16,'9000000000002','Ana','Torres','55551001','1990-03-12','F','IGSS-1001'),(17,'9000000000003','Carlos','Ramirez','',NULL,'',NULL),(18,'9000000000004','Maria','Lopez','55551003','1985-07-20','F',NULL),(19,'9000000000005','Pedro','Ramirez','55551004',NULL,'M',NULL),(20,'9000000000006','Lucia','Fernandez','55551005','1978-11-02','F',NULL),(21,'9000000000007','Jorge','Morales','','1995-05-30','M',NULL),(22,'9000000000008','Sofia','Guzman','',NULL,'',NULL),(23,'9000000000009','Diego','Morales','55551008','2001-01-15','M','IGSS-1008'),(24,'9000000000010','Valentina','Castillo','55551009','1999-09-09','',NULL),(25,'9000000000011','Roberto','Gomez','55551010','1982-04-18','M',NULL);
/*!40000 ALTER TABLE `pacientes` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `permisos`
--

DROP TABLE IF EXISTS `permisos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `permisos` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int NOT NULL,
  `codename` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `tipos_contenido` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=41 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `permisos`
--

LOCK TABLES `permisos` WRITE;
/*!40000 ALTER TABLE `permisos` DISABLE KEYS */;
INSERT INTO `permisos` VALUES (1,'Can add log entry',1,'add_logentry'),(2,'Can change log entry',1,'change_logentry'),(3,'Can delete log entry',1,'delete_logentry'),(4,'Can view log entry',1,'view_logentry'),(5,'Can add permission',2,'add_permission'),(6,'Can change permission',2,'change_permission'),(7,'Can delete permission',2,'delete_permission'),(8,'Can view permission',2,'view_permission'),(9,'Can add group',3,'add_group'),(10,'Can change group',3,'change_group'),(11,'Can delete group',3,'delete_group'),(12,'Can view group',3,'view_group'),(13,'Can add content type',4,'add_contenttype'),(14,'Can change content type',4,'change_contenttype'),(15,'Can delete content type',4,'delete_contenttype'),(16,'Can view content type',4,'view_contenttype'),(17,'Can add session',5,'add_session'),(18,'Can change session',5,'change_session'),(19,'Can delete session',5,'delete_session'),(20,'Can view session',5,'view_session'),(21,'Can add usuario',6,'add_usuario'),(22,'Can change usuario',6,'change_usuario'),(23,'Can delete usuario',6,'delete_usuario'),(24,'Can view usuario',6,'view_usuario'),(25,'Can add paciente',7,'add_paciente'),(26,'Can change paciente',7,'change_paciente'),(27,'Can delete paciente',7,'delete_paciente'),(28,'Can view paciente',7,'view_paciente'),(29,'Can add tipo de estudio',8,'add_tipoestudio'),(30,'Can change tipo de estudio',8,'change_tipoestudio'),(31,'Can delete tipo de estudio',8,'delete_tipoestudio'),(32,'Can view tipo de estudio',8,'view_tipoestudio'),(33,'Can add cita',9,'add_cita'),(34,'Can change cita',9,'change_cita'),(35,'Can delete cita',9,'delete_cita'),(36,'Can view cita',9,'view_cita'),(37,'Can add orden de trabajo',10,'add_ordentrabajo'),(38,'Can change orden de trabajo',10,'change_ordentrabajo'),(39,'Can delete orden de trabajo',10,'delete_ordentrabajo'),(40,'Can view orden de trabajo',10,'view_ordentrabajo');
/*!40000 ALTER TABLE `permisos` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `registros_admin`
--

DROP TABLE IF EXISTS `registros_admin`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `registros_admin` (
  `id` int NOT NULL AUTO_INCREMENT,
  `action_time` datetime(6) NOT NULL,
  `object_id` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  `object_repr` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `action_flag` smallint unsigned NOT NULL,
  `change_message` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int DEFAULT NULL,
  `user_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `django_admin_log_content_type_id_c4bce8eb_fk_django_co` (`content_type_id`),
  KEY `django_admin_log_user_id_c564eba6_fk_usuarios_id` (`user_id`),
  CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `tipos_contenido` (`id`),
  CONSTRAINT `django_admin_log_user_id_c564eba6_fk_usuarios_id` FOREIGN KEY (`user_id`) REFERENCES `usuarios` (`id`),
  CONSTRAINT `registros_admin_chk_1` CHECK ((`action_flag` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `registros_admin`
--

LOCK TABLES `registros_admin` WRITE;
/*!40000 ALTER TABLE `registros_admin` DISABLE KEYS */;
/*!40000 ALTER TABLE `registros_admin` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `reportes_diarios`
--

DROP TABLE IF EXISTS `reportes_diarios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `reportes_diarios` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `fecha` date NOT NULL,
  `convenio` varchar(20) NOT NULL,
  `estado` varchar(20) NOT NULL,
  `enviado_en` datetime(6) DEFAULT NULL,
  `enviado_por_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `reportes_diarios_fecha_convenio_483660c9_uniq` (`fecha`,`convenio`),
  KEY `reportes_diarios_enviado_por_id_1f402642_fk_usuarios_id` (`enviado_por_id`),
  CONSTRAINT `reportes_diarios_enviado_por_id_1f402642_fk_usuarios_id` FOREIGN KEY (`enviado_por_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `reportes_diarios`
--

LOCK TABLES `reportes_diarios` WRITE;
/*!40000 ALTER TABLE `reportes_diarios` DISABLE KEYS */;
INSERT INTO `reportes_diarios` VALUES (2,'2026-08-03','coex','borrador',NULL,NULL),(3,'2026-07-31','coex','borrador',NULL,NULL),(4,'2026-07-28','coex','borrador',NULL,NULL),(5,'2026-07-27','coex','borrador',NULL,NULL),(6,'2026-08-21','coex','enviado','2026-08-21 23:51:46.212388',3),(8,'2026-07-27','privado','borrador',NULL,NULL),(9,'2026-07-28','privado','borrador',NULL,NULL),(10,'2026-07-29','privado','borrador',NULL,NULL),(11,'2026-07-30','privado','borrador',NULL,NULL),(12,'2026-07-31','privado','borrador',NULL,NULL),(13,'2026-08-01','privado','borrador',NULL,NULL),(14,'2026-08-24','coex','borrador',NULL,NULL);
/*!40000 ALTER TABLE `reportes_diarios` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `secuencias_diarias_tickets`
--

DROP TABLE IF EXISTS `secuencias_diarias_tickets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `secuencias_diarias_tickets` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `servicio` varchar(20) NOT NULL,
  `fecha` date NOT NULL,
  `ultimo` int unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `secuencias_diarias_tickets_servicio_fecha_039f664b_uniq` (`servicio`,`fecha`),
  CONSTRAINT `secuencias_diarias_tickets_chk_1` CHECK ((`ultimo` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `secuencias_diarias_tickets`
--

LOCK TABLES `secuencias_diarias_tickets` WRITE;
/*!40000 ALTER TABLE `secuencias_diarias_tickets` DISABLE KEYS */;
INSERT INTO `secuencias_diarias_tickets` VALUES (1,'emergencia_igss','2026-08-22',1);
/*!40000 ALTER TABLE `secuencias_diarias_tickets` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sesiones`
--

DROP TABLE IF EXISTS `sesiones`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sesiones` (
  `session_key` varchar(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `session_data` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`),
  KEY `django_session_expire_date_a5c62663` (`expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sesiones`
--

LOCK TABLES `sesiones` WRITE;
/*!40000 ALTER TABLE `sesiones` DISABLE KEYS */;
INSERT INTO `sesiones` VALUES ('02hxw10r43ie5zxx95gyvntxzlwev4o2','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxq5A:yXuBlcKX_64XXjthYzY21f79GbW4pY9HG7mc9jxkrBE','2026-09-05 18:04:40.705380'),('0hdm10m3jwyrh90srbau06w2fy7gg595','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqCI:qJYYeM2pgT1OBNB-YywJGZ7exhsnk_116CRzcsDufSw','2026-09-05 18:12:02.513476'),('1otskpjcwhg0j9nql465ep014ait4i7i','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpwx:4PYwXM4mf60qPXDe_UO5Mt_ESNInvUnc0JHgVsI-OzA','2026-09-05 17:56:11.558756'),('2j1yza23vbx79mlbzp4q6va7j7l8swno','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpjn:araoKDa_S1WLHAJq-6zJ9SN5iREL1Lu8Fu7UFIxRLxE','2026-09-05 17:42:35.929822'),('2jbehn218h21jgpgmc02friwquvv6dgo','.eJxVjMsOwiAQRf-FtSHAFDK4dO83kBkeUjWQlHZl_Hdt0oVu7znnvkSgba1hG3kJcxJnYcTpd2OKj9x2kO7Ubl3G3tZlZrkr8qBDXnvKz8vh_h1UGvVbk-MJAexEXqNh1MVmpJSBPCjPybFBC-A4RiJvYlHFGtYOidgzK_H-AOIYOFM:1woaMf:sTIsUWyNeygWE6bFAgy5sJwCZ2iKptLCtof48NrYIOU','2026-08-11 05:28:29.644592'),('2y1cn78k1yycjacxjryswb1ofwyaoicm','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxmnP:wDXfDCXdud4vlUi93hPYps5erpoezqRfgAWXTa11iw4','2026-09-05 14:34:07.127911'),('3yn7rw8zq4rz3cg82o3n7hy772ohxj4t','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqLp:4UvUngjkPft9TX38B2wKWK_dygmVcDRHkXpdCDSx_sk','2026-09-05 18:21:53.291979'),('418m9eqb4pqqcso5rf26q2ypmovdha18','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqWY:Ma9576meJ_hHeMyH8RLFUBQkFl8EY9CliOEKN8NOxkQ','2026-09-05 18:32:58.659749'),('4zt1mmr1m7pxru31tpudw29rt1pi87ju','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxq4y:KgBPRQzTFly5KxmtuABFqsOW1dllCOcU8jmkGShxIS4','2026-09-05 18:04:28.562220'),('56d82vrpjjh23q2smjemist2nj20r737','.eJxVjMsOwiAQAP-FsyHQ8igevfcbyC67SNXQpLQn478bkh70OjOZt4hw7CUejbe4kLgKLS6_DCE9uXZBD6j3Vaa17tuCsifytE3OK_HrdrZ_gwKt9C0BDD5pJB3U4HLSnNk744knRZZcysYYa5Ui54LDbMYwjZzBog1Gofh8AfOROAc:1wxqTK:5C5ZM1eeLjIlQokgbNwzDpCU-AiBpS3H5GyUQicuTyY','2026-09-05 18:29:38.332986'),('5gbjlcsjtllw98fzmdyv6hh3ezazhx65','.eJxVjMsOwiAQAP-FsyHQ8igevfcbyC67SNXQpLQn478bkh70OjOZt4hw7CUejbe4kLgKLS6_DCE9uXZBD6j3Vaa17tuCsifytE3OK_HrdrZ_gwKt9C0BDD5pJB3U4HLSnNk744knRZZcysYYa5Ui54LDbMYwjZzBog1Gofh8AfOROAc:1wxmkd:16wmHoaqkOwYEZwTks0CNa4_SrFy2OwnpJEWJOu9p7o','2026-09-05 14:31:15.467874'),('60di2fbdc4tzcq28lkhemp71unxqlph9','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxlzb:bkZ9eIJAoBdO3368ewXZg_q4QoQzReleOehOHQ_Mr1g','2026-09-05 13:42:39.300302'),('61iti3jejx6uk9rsvce9gp9b1gbzpyaw','.eJxVjDsOwyAQBe9CHSHAy8cp0_sMaGEhOIlAMnYV5e6xJRdJ-2bevJnHbS1-62nxM7Erk8Auv2PA-Ez1IPTAem88trouc-CHwk_a-dQovW6n-xco2Mv-HrXL0QgI2oIWoDXIYPVgXZLSUlBKYTZ278GIZIQ02Q2kEEjlnIGAfb7fnjen:1wxYgS:CodyWu1_rpyjw__PGTIiyUPL6uRFTtZt-Jd_PmL5N2E','2026-09-04 23:30:00.632000'),('68we69llggj26jtxvcp9cbn4vxe135d7','.eJxVjDsOwyAQBe9CHSHAy8cp0_sMaGEhOIlAMnYV5e6xJRdJ-2bevJnHbS1-62nxM7Erk8Auv2PA-Ez1IPTAem88trouc-CHwk_a-dQovW6n-xco2Mv-HrXL0QgI2oIWoDXIYPVgXZLSUlBKYTZ278GIZIQ02Q2kEEjlnIGAfb7fnjen:1wxYhS:gF1cjiFjshsUC7pPfIkAEnJCMAnBVK3ei7B67d-yN6c','2026-09-04 23:31:02.505697'),('6neol59fpra6ftnsmhnth84xskmix5mw','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpnL:OGGL28-qIhLS0CqrN1HcXJBfPu3Q5b3r5M_eL7MRWiw','2026-09-05 17:46:15.643924'),('6tvjnd5k0kf1xgg6z55r076lrlv7xjpg','.eJxVjMsOwiAQAP-FsyHQ8igevfcbyC67SNXQpLQn478bkh70OjOZt4hw7CUejbe4kLgKLS6_DCE9uXZBD6j3Vaa17tuCsifytE3OK_HrdrZ_gwKt9C0BDD5pJB3U4HLSnNk744knRZZcysYYa5Ui54LDbMYwjZzBog1Gofh8AfOROAc:1wxmkr:Oz1PsIjLtdAIEg-lRzph7s0_FXRX29Duh5xTmcTAbGU','2026-09-05 14:31:29.562574'),('70outur44kgruax4w5n4i90mu9xjjb7x','.eJxVjMsOwiAUBf-FtSGFgoBL9_0GcrmHStVA0sfK-O_apAvdnpk5LxFpW0vcljzHCeIinDj9bon4kesOcKd6a5JbXecpyV2RB13k0JCf18P9Oyi0lG8dSGlwcF1CMGz6URkF6oyF8YDXDmTzCOqhrAcl7f3ZsQ2smblLQbw_9eo4lg:1wxq6U:svVHON_p2kr0Xt7J2x1RH9OWpr5pRk0kksse56r01og','2026-09-05 18:06:02.932686'),('7z48elz4h9fc00xtcv2muwmtwfvge8m9','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxlzk:vBWCIJYMCmamWMaj-Z7ZDqLoHNIEgrft6DOjdnUSFVg','2026-09-05 13:42:48.915691'),('8zb25lhwmj1t6tyrcfqkuhtpil39m0d9','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpiN:2ahp8QOGbT5hs4YlxOGwYT2Dax4PG53xuw3XYi3JDho','2026-09-05 17:41:07.683663'),('926r4n5h4fp5ke05dsd1ivxbdpn2kh4s','.eJxVjMsOwiAQRf-FtSFQ3i7d-w1khgGpGkhKuzL-uzbpQrf3nHNfLMK21riNvMSZ2JlJz06_I0J65LYTukO7dZ56W5cZ-a7wgw5-7ZSfl8P9O6gw6rd21oDTAiEIUyYflLLZYEARyJBEINTSkTJobdJiMqWQK5pC8tqS18jeH_2yOBk:1wxmdb:Q2FTJYMGPZKorRKNnaVVNF6q4CU5vuqyuGyfkuojMow','2026-09-05 14:23:59.841176'),('a93cwk316m3it00561emm0t830iv0d8o','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqfh:MmNWyn6JULrPn4uRn2XhNyL51FpRBmHuIW8kvIGtNgE','2026-09-05 18:42:25.364760'),('bowsjdp9mqm694sdebjubeh77rs7w8bd','.eJxVjMsOwiAQRf-FtSFQ3i7d-w1khgGpGkhKuzL-uzbpQrf3nHNfLMK21riNvMSZ2JlJz06_I0J65LYTukO7dZ56W5cZ-a7wgw5-7ZSfl8P9O6gw6rd21oDTAiEIUyYflLLZYEARyJBEINTSkTJobdJiMqWQK5pC8tqS18jeH_2yOBk:1wxmcv:QnFBlxvTlvdew_SxqT_Bno14Yjzv3VZgRRk6SWDT-sU','2026-09-05 14:23:17.933445'),('buekxodkl15osl43cjt4536soxvqyirq','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wpg4z:O2msxy9H-tnXfLkzcgVN9JRvxT0s11PjCERtfssi-_Q','2026-08-14 05:46:45.874583'),('en8kgejtt7r1socncduihe4821s15dmw','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpfl:8PCfHfuH35GgfoSz8IRElLnE91xBfLTrUtdBtFxwXeY','2026-09-05 17:38:25.330328'),('fdlmje2bkg5gdptqeo3xd4p17f1ih5bq','.eJxVjMsOwiAUBf-FtSGFgoBL9_0GcrmHStVA0sfK-O_apAvdnpk5LxFpW0vcljzHCeIinDj9bon4kesOcKd6a5JbXecpyV2RB13k0JCf18P9Oyi0lG8dSGlwcF1CMGz6URkF6oyF8YDXDmTzCOqhrAcl7f3ZsQ2smblLQbw_9eo4lg:1wpdPu:KQGKYBZCwvHd2z8DkVYXYD3dvCljm9eOOTELDIf89cg','2026-08-14 02:56:10.060048'),('fou5amp10q4d2w9rfvsc8r8616bhwryc','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqMN:8uvUrDONHb74Zb0RbzfdPvUSPNmwM0kmXJFXbvSSoxk','2026-09-05 18:22:27.164559'),('ghwhsr3nczs0s0yv4nnu2kf8fmkiwxkm','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wpg2x:HAFc_0YJo_Mds80jguJa-d6twcz2NWJgAOIjdVQxMM8','2026-08-14 05:44:39.442299'),('gjkpct5sqtd4dsaoob15jbd20mv8fp8v','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpwi:V8LZ8OEsM6B0bgFfABzbVFgeNjEC1c3trntdHJPDmC0','2026-09-05 17:55:56.359467'),('h6p4meowpgkaa3dbnbqdjbccgb40zxid','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxrez:63_CLUWaVye_keXrhUo0worznz1mJ3RxLVuIaaXJIYU','2026-09-05 19:45:45.408691'),('hb77z17x1tbw81yw9ymjzi2trd784y86','.eJxVjMsOwiAURP-FtSEicAGX7v0Gch8oVUOT0q6M_26bdKGrSeacmbfKuMw1L71MeRB1VgbU4bck5GdpG5EHtvuoeWzzNJDeFL3Trq-jlNdld_8OKva6rtnKzcdg1mBbKAGjiUzuaCX4JBEtWYhRwDk6kdjgDDgoIRBAKp7V5wsagDgg:1wxYgR:zjn46cZ-S-gSjxdDxN50gjmV-c2b20v3a7xO_js5bec','2026-09-04 23:29:59.724181'),('ib4amkjga8kgx1shycsyihb4bs4743o9','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxmcg:5Fw2QC896BP9Y4iLtkVKIpMtcOp2zZ_tPLa-IfR3K4o','2026-09-05 14:23:02.300963'),('ikwa91n9bnyqvo8ew7lbtqkh6tqdgfzt','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqM3:nGhW51oNxfrVNLlCFzqWcxY7GBJGeVgnJZ-qry7C9cs','2026-09-05 18:22:07.168997'),('ili2ipv4pqab2capsrtya68l0te8axww','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxlZm:9DlT9oLwwNavJLWtVozFJjC2ynjesAbhWdnxiEHjB4A','2026-09-05 13:15:58.831714'),('jei0kyofqh1hlhorpwlpd38dyps52kc2','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxmnC:f73hgBOecg-PghVeB_lBUXtAd6Sqjw08gNCDq9XqxXA','2026-09-05 14:33:54.855168'),('krflxqvxtmk4wew231qx18c6tyzwseji','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxmnX:xf89MzhpM-Z91OvEzmyMT9BMynq8Vtz1Nj93mxfVc6o','2026-09-05 14:34:15.139277'),('kvsqu4xrywqs1kv4wlhiont3gvnc2ly5','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqCp:4n2Qa5RJnCcgcX3Ny1I5khyooGOOOQhtuc_oUOcHOas','2026-09-05 18:12:35.870769'),('kzpl3y53pgyeyzat2acax09kdk4cs6bo','.eJxVjMsOwiAURP-FtSEicAGX7v0Gch8oVUOT0q6M_26bdKGrSeacmbfKuMw1L71MeRB1VgbU4bck5GdpG5EHtvuoeWzzNJDeFL3Trq-jlNdld_8OKva6rtnKzcdg1mBbKAGjiUzuaCX4JBEtWYhRwDk6kdjgDDgoIRBAKp7V5wsagDgg:1wxYhR:M5efvoRzH0i5lQgnFE0rjqN5BnA1pcr4dmXfoKv490M','2026-09-04 23:31:01.438111'),('l3zvhtc4bi317dho6shrkg0v7vbv78b6','.eJxVjDsOwyAQRO9CHSGw-aZM7zOgBXaDkwgkY1dR7h5bcpGUM-_NvFmAbS1h67iEObMrGwS7_JYR0hPrQfID6r3x1Oq6zJEfCj9p51PL-Lqd7t9BgV72dcwkFVL01mgDbg9GKDcqchK0St7YqMaBIoAVUlPWSNoRWkxeKDMi-3wBDPQ4Sg:1wxZXD:AQVIvav69_-O8D3P-wyH7PzD73oJ6p4Se0p1LRMX96A','2026-09-05 00:24:31.163369'),('lxjk721tcryuglm0xmdyl8lhis736egn','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqLQ:os8vX4iX67I47chO9jhBYHoW4aK8ekEgMu7rSzUjopQ','2026-09-05 18:21:28.031350'),('nrxpkm7om8pbwef1d5la4f6vnubiz7hy','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqfz:kNGov8G1mgdGXYBe2s7gXe45yRENdrN3YLrRISwHii0','2026-09-05 18:42:43.788620'),('o7peeeexfgoaeqzxrvqfj6zdg6apu02x','.eJxVjMsOwiAURP-FtSEicAGX7v0Gch8oVUOT0q6M_26bdKGrSeacmbfKuMw1L71MeRB1VgbU4bck5GdpG5EHtvuoeWzzNJDeFL3Trq-jlNdld_8OKva6rtnKzcdg1mBbKAGjiUzuaCX4JBEtWYhRwDk6kdjgDDgoIRBAKp7V5wsagDgg:1wxYgu:bknqSx_lEKVZI5dTq8E2WuOwQSVc_KmCPlm0gwkqX8A','2026-09-04 23:30:28.383463'),('okn5srp98h1xbgvj2bysbydzgg7v2ucw','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpkd:oX4NM5Jb9O9K8Z9V_0H359b1rAjSs1-952LelCvyLF4','2026-09-05 17:43:27.359544'),('sje493wug0mpn4c362hp0uhgowcyf1yk','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1woaUV:fXk0rS86HpJbXkUrTv9DOvs3xnxeGsbMfJLUBTtPJQU','2026-08-11 05:36:35.426200'),('sva3dppm5wsrxjqu1xqy24kmb1krei24','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqC3:xKKWpBDNnI2PySiZblYtwcMvsZjgQ6i6CdOdtLyYQFA','2026-09-05 18:11:47.796577'),('tja2eimwb8276eb7wmvjhyfl0zcbplne','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpxC:YqqQokA2k4W032m3h9wmkyinbFAFeT3JrrF4HtGCrV0','2026-09-05 17:56:26.062813'),('tmlfxuia4sa7sq8l1dofkdy9615k43ca','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpgP:vxXq8U8aX4CUpYviXC6DBRu1Z9pTaog5TV-lokIO9Yk','2026-09-05 17:39:05.951423'),('txg07v1ffqf7qvqjfzibs2zhg32tgzzr','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxrZQ:LLCBnTEgBglUAl1i15NjMSbC2828wr-J1u1UoekcjiY','2026-09-05 19:40:00.386905'),('u8ov1csrbo0ixvkh7zfmlxw6pm6axlic','.eJxVjMsOwiAQRf-FtSFQ3i7d-w1khgGpGkhKuzL-uzbpQrf3nHNfLMK21riNvMSZ2JlJz06_I0J65LYTukO7dZ56W5cZ-a7wgw5-7ZSfl8P9O6gw6rd21oDTAiEIUyYflLLZYEARyJBEINTSkTJobdJiMqWQK5pC8tqS18jeH_2yOBk:1wxmgk:uLlqLS4XE8g7qPEQBRl_xwSwIv4n2m4P-ocnYn1ZJmI','2026-09-05 14:27:14.379873'),('ucj6qpa7t343r8ewnp3zpttr3lhiqtjn','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpg7:vCYojfElyl2cIsAnv6OMk1tWpFYGKzVjy3PwnnaW64k','2026-09-05 17:38:47.395777'),('ui9fykktbdhw1c7lrmpsalua82ynv2ha','.eJxVjMsOwiAURP-FtSEicAGX7v0Gch8oVUOT0q6M_26bdKGrSeacmbfKuMw1L71MeRB1VgbU4bck5GdpG5EHtvuoeWzzNJDeFL3Trq-jlNdld_8OKva6rtnKzcdg1mBbKAGjiUzuaCX4JBEtWYhRwDk6kdjgDDgoIRBAKp7V5wsagDgg:1wxYfS:s--DIjExOrSK0gIKtlOjLnEPT8YZeUl_rDjtW9pWGgI','2026-09-04 23:28:58.509194'),('ulkpenciifzzu68pcral8udajoix0zye','.eJxVjM0OwiAQhN-FsyELrfx49O4zkN0uSNVAUtqT8d2lSQ-azGm-b-YtAm5rDluLS5hZXIQTp9-OcHrGsgN-YLlXOdWyLjPJXZEHbfJWOb6uh_t3kLHlvkZH1GMNJqPViCZpUFYpIBO1TR4jwsiRQAGM5Nh4OBN3dcCJ_WDF5wvwujfm:1wpdae:LlBiIOayN1ynXvqaioRi78FgMV-ZbapQHBw-gmQ0wls','2026-08-14 03:07:16.520241'),('uvocws60a3qfydhhr434jn8nazevh8u6','.eJxVjDsOwyAQBe9CHSHAy8cp0_sMaGEhOIlAMnYV5e6xJRdJ-2bevJnHbS1-62nxM7Erk8Auv2PA-Ez1IPTAem88trouc-CHwk_a-dQovW6n-xco2Mv-HrXL0QgI2oIWoDXIYPVgXZLSUlBKYTZ278GIZIQ02Q2kEEjlnIGAfb7fnjen:1wxYhi:jB0SphcLM4r60uAbst535myiCJOUuKzAIElMyswvYu8','2026-09-04 23:31:18.791570'),('vzdswr9gpvisgxdx75igu2btc8il316d','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxpT6:sxUalcSUyZZ0ijm_1QAi5chTiR2CHMKrAJ4qAHfr3vc','2026-09-05 17:25:20.221242'),('x3ujiwpbg6ts5ocjyhya66pg5ji5u687','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxqTc:KVg7K603wLVpBlh4gzPqgQ-Z8xUNpP-GetvAf87daLM','2026-09-05 18:29:56.680180'),('xeru58q3p9lb6hindi54rdi3wjdhvzyj','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxphb:5aw9LKW6YE6jPE2efrS2vY9ZT0v0zcHR9pVx7xImHSM','2026-09-05 17:40:19.345073'),('xjii0e9pg9jergv7sjl9n13cmiycb3ff','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxmgk:hMIjehNYiZns19wlpDkfRwqChPsOrH2Xpc1J9jHI2b0','2026-09-05 14:27:14.240420'),('y6i3zzdx0w005e70uv2xbmumpq4nb6fq','.eJxVjMsOgjAURP-la9PQN3Xpnm9o7qNY1JSEwsr470LCQleTzDkzb5FgW0vaWl7SxOIqjLj8dgj0zPUA_IB6nyXNdV0mlIciT9rkMHN-3U7376BAK_s662Ct7qOFQN5FZxwEBRjCHh3iyIqZetYczYhkvO58VBS9AgYPqMTnC9ZmN_w:1wxrk8:_ZsLVQgedQ_uHC_js_MeP-iOuv_VNZzUFtAQ8-OWTyI','2026-09-05 19:51:04.556102'),('z7qhjbi2wbr7ip9nbif73mu5dpzfu4ll','.eJxVjMsOwiAQRf-FtSEwvF269xvIAINUDU1KuzL-uzbpQrf3nHNfLOK2trgNWuJU2JmBZKffMWF-UN9JuWO_zTzPfV2mxHeFH3Tw61zoeTncv4OGo33rqpLFaiqEknTNWalSrDOaSFkLrhoBuaZMUoAXJLwK2gZ00hqlPQjN3h8h8zep:1wxphE:4ubtQfluQeZD9S-sKEQxXjoA_lcmUyzdIRCnW-YDwvc','2026-09-05 17:39:56.180748'),('z8hq3ajmqdfdmudikv3ohi78t3sjkhoj','.eJxVjMsOwiAQAP-FsyHQ8igevfcbyC67SNXQpLQn478bkh70OjOZt4hw7CUejbe4kLgKLS6_DCE9uXZBD6j3Vaa17tuCsifytE3OK_HrdrZ_gwKt9C0BDD5pJB3U4HLSnNk744knRZZcysYYa5Ui54LDbMYwjZzBog1Gofh8AfOROAc:1wxqTc:zOhNNuoqy1DOito3u1qnxFnAvMckmmK4-MrcXgHUUi4','2026-09-05 18:29:56.545808');
/*!40000 ALTER TABLE `sesiones` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tickets`
--

DROP TABLE IF EXISTS `tickets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tickets` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `servicio` varchar(20) NOT NULL,
  `prioridad` smallint unsigned NOT NULL,
  `estado` varchar(20) NOT NULL,
  `numero` int unsigned NOT NULL,
  `turno` varchar(20) NOT NULL,
  `motivo` varchar(255) NOT NULL,
  `creado_en` datetime(6) NOT NULL,
  `atendido_en` datetime(6) DEFAULT NULL,
  `paciente_id` bigint NOT NULL,
  `registrado_por_id` bigint NOT NULL,
  `cita_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tickets_paciente_id_350aa8ae_fk_pacientes_id` (`paciente_id`),
  KEY `tickets_registrado_por_id_86c9ab40_fk_usuarios_id` (`registrado_por_id`),
  KEY `tickets_cita_id_532731b7_fk_citas_id` (`cita_id`),
  CONSTRAINT `tickets_cita_id_532731b7_fk_citas_id` FOREIGN KEY (`cita_id`) REFERENCES `citas` (`id`),
  CONSTRAINT `tickets_paciente_id_350aa8ae_fk_pacientes_id` FOREIGN KEY (`paciente_id`) REFERENCES `pacientes` (`id`),
  CONSTRAINT `tickets_registrado_por_id_86c9ab40_fk_usuarios_id` FOREIGN KEY (`registrado_por_id`) REFERENCES `usuarios` (`id`),
  CONSTRAINT `tickets_chk_1` CHECK ((`prioridad` >= 0)),
  CONSTRAINT `tickets_chk_2` CHECK ((`numero` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tickets`
--

LOCK TABLES `tickets` WRITE;
/*!40000 ALTER TABLE `tickets` DISABLE KEYS */;
INSERT INTO `tickets` VALUES (1,'emergencia_igss',2,'en_espera',1,'EMER-001','Golpe fuerte en la cabeza, mareos.','2026-08-22 17:49:47.327658',NULL,23,3,NULL);
/*!40000 ALTER TABLE `tickets` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tipos_contenido`
--

DROP TABLE IF EXISTS `tipos_contenido`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tipos_contenido` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `model` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tipos_contenido`
--

LOCK TABLES `tipos_contenido` WRITE;
/*!40000 ALTER TABLE `tipos_contenido` DISABLE KEYS */;
INSERT INTO `tipos_contenido` VALUES (6,'accounts','usuario'),(1,'admin','logentry'),(3,'auth','group'),(2,'auth','permission'),(4,'contenttypes','contenttype'),(9,'pacientes','cita'),(10,'pacientes','ordentrabajo'),(7,'pacientes','paciente'),(8,'pacientes','tipoestudio'),(5,'sessions','session');
/*!40000 ALTER TABLE `tipos_contenido` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tipos_estudio`
--

DROP TABLE IF EXISTS `tipos_estudio`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tipos_estudio` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `nombre` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `precio` decimal(8,2) NOT NULL,
  `activo` tinyint(1) NOT NULL,
  `duracion_minutos` int unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `nombre` (`nombre`),
  CONSTRAINT `tipos_estudio_chk_1` CHECK ((`duracion_minutos` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tipos_estudio`
--

LOCK TABLES `tipos_estudio` WRITE;
/*!40000 ALTER TABLE `tipos_estudio` DISABLE KEYS */;
INSERT INTO `tipos_estudio` VALUES (1,'Rayos X',0.00,0,30),(2,'Ultrasonido',0.00,0,30),(3,'Tomografía',0.00,0,30),(4,'Resonancia',0.00,0,30),(6,'Tórax',112.00,1,30),(7,'Rayos X rodilla',112.00,1,15),(8,'USG tiroideo',200.00,1,30),(9,'Rayos X pie',224.00,1,15),(10,'Rayos X de columna lumbar',240.00,1,20),(11,'Rayos X COLUMNA DORSOLUMBAR NIÑOS',280.00,1,25),(12,'Rayos X COL. LUMBOSACRA AP LATERAL Y OBLICUAS',400.00,1,25),(13,'Rayos X abdomen AP',200.00,1,25),(14,'TAC de cráneo',1400.00,1,45),(15,'TAC de abdomen completo',2600.00,1,60);
/*!40000 ALTER TABLE `tipos_estudio` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tipos_estudio_radiologos`
--

DROP TABLE IF EXISTS `tipos_estudio_radiologos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tipos_estudio_radiologos` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `tipoestudio_id` bigint NOT NULL,
  `usuario_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tipos_estudio_radiologos_tipoestudio_id_usuario_id_f6a90ab9_uniq` (`tipoestudio_id`,`usuario_id`),
  KEY `tipos_estudio_radiologos_usuario_id_dc073a67_fk_usuarios_id` (`usuario_id`),
  CONSTRAINT `tipos_estudio_radiol_tipoestudio_id_d56a5f3f_fk_tipos_est` FOREIGN KEY (`tipoestudio_id`) REFERENCES `tipos_estudio` (`id`),
  CONSTRAINT `tipos_estudio_radiologos_usuario_id_dc073a67_fk_usuarios_id` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tipos_estudio_radiologos`
--

LOCK TABLES `tipos_estudio_radiologos` WRITE;
/*!40000 ALTER TABLE `tipos_estudio_radiologos` DISABLE KEYS */;
INSERT INTO `tipos_estudio_radiologos` VALUES (2,6,7),(3,7,7),(4,8,7),(5,9,7),(6,10,7),(7,11,7),(8,12,7),(9,13,7),(10,14,7),(11,15,7);
/*!40000 ALTER TABLE `tipos_estudio_radiologos` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `usuarios`
--

DROP TABLE IF EXISTS `usuarios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `usuarios` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `password` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `username` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `first_name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(150) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(254) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL,
  `rol` varchar(25) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `porcentaje_coex` decimal(5,2) NOT NULL,
  `porcentaje_emergencia_igss` decimal(5,2) NOT NULL,
  `porcentaje_privado` decimal(5,2) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `usuarios`
--

LOCK TABLES `usuarios` WRITE;
/*!40000 ALTER TABLE `usuarios` DISABLE KEYS */;
INSERT INTO `usuarios` VALUES (1,'pbkdf2_sha256$1000000$nd11OJVavwESXugykppf6m$VdCnNmZn3Jn/86ys7SPIq9XA3H1LHyWYz+ypJ8DXYmk=','2026-08-22 18:29:56.529878',1,'admin','','','admin@clinica.local',1,1,'2026-07-28 03:10:34.957321','administrador',0.00,0.00,0.00),(2,'pbkdf2_sha256$1000000$53oUDa8RCT647VHhgb5mgn$c8foey66c6vQ/gU23buPs3YcoRrOsEeE2ZLm4r0ADYo=','2026-08-22 18:26:50.166023',0,'tecnico1','Juan','Perez','tecnico1@clinica.local',0,1,'2026-07-28 03:33:09.704979','tecnico_imagenes',0.00,0.00,0.00),(3,'pbkdf2_sha256$1000000$OiNQ99G0nBw7Hfqqo4Wcld$ONuu1pSShhQB6TP26rYR3xxU9f1Z0ak6n+7HqXw8dnk=','2026-08-22 19:51:04.540577',0,'Elmer','Elmer Adrián','Melendrez Catalan','elmeradrianctalan@gmail.com',0,1,'2026-07-28 03:36:40.973107','recepcionista',0.00,0.00,0.00),(4,'pbkdf2_sha256$1000000$aSFXg5keV37wGEsK1Ts1PK$ojepQqtpr8iPmK6hIMsdJVk6hElnOGAoXoSuqtnSens=','2026-08-21 22:44:57.680935',0,'marilin','Marilin Adriana','Yaque Henandez','marilin@gmail.com',0,1,'2026-07-28 03:47:09.530490','tecnico_imagenes',0.00,0.00,0.00),(5,'pbkdf2_sha256$1000000$FLBb2pI4ahYEDIiW9UTqa0$G+6f5rB4pfAjoeo3rou/sAdx2JFCuTN0cgRxVfZEeus=','2026-07-28 05:26:44.402108',0,'tecnico_img','','','',0,1,'2026-07-28 05:24:21.937156','tecnico_imagenes',0.00,0.00,0.00),(7,'pbkdf2_sha256$1000000$MbxWKSoizWN2CuJ8wnzCvY$dKbsBQTFojLvOESlLLOPQKw2atn6KxOQ5YdPEyWEnDw=','2026-08-22 18:32:35.627950',0,'radiologo1','','','',0,1,'2026-07-31 02:51:25.224545','medico_radiologo',0.00,0.00,0.00),(9,'pbkdf2_sha256$1000000$CEZcQmoAZfR56922QDToZ2$DL7Z9sR+wI8xJaSObcrvQtzJ0HvcLkrwPvyHS1eiZlI=',NULL,1,'Mayh','','','adriana123@gmail.com',1,1,'2026-08-20 21:03:30.041741','administrador',0.00,0.00,0.00),(17,'pbkdf2_sha256$1000000$1hGnf0MwIYv5ye6NOeJBpS$yBGhUBC6EMi7Ymf1RJL+TnTDLB4+SNg1hisS7Ka+oTQ=','2026-08-21 23:47:23.225157',1,'Adriana','','','adri123@gmail.com',1,1,'2026-08-21 23:42:56.120573','administrador',0.00,0.00,0.00),(18,'pbkdf2_sha256$1000000$3fFVMK8hNKtoc0QK8Argvm$PckaU1Uj7fq3HkvT3dWtXYZbcAwi9faL4t2ZXzhn5h4=','2026-08-22 14:27:14.371840',0,'Roberto','Roberto','Galindo','robertogalindo@gmail.com',0,1,'2026-08-21 23:49:34.717105','administrador_financiero',0.00,0.00,0.00),(22,'pbkdf2_sha256$1000000$Kz8OZd7Obbb7r1LcXu7z2n$DmbJ8O0VXaemBBmeeCgoccJlUEjFGfoVHBS8KdOUlmc=',NULL,0,'verificacion_visual','Prueba','Visual','',0,1,'2026-08-22 17:43:34.514142','recepcionista',0.00,0.00,0.00);
/*!40000 ALTER TABLE `usuarios` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `usuarios_grupos`
--

DROP TABLE IF EXISTS `usuarios_grupos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `usuarios_grupos` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `usuario_id` bigint NOT NULL,
  `group_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `usuarios_grupos_usuario_id_group_id_1097394d_uniq` (`usuario_id`,`group_id`),
  KEY `usuarios_grupos_group_id_f7bf68b7_fk_auth_group_id` (`group_id`),
  CONSTRAINT `usuarios_grupos_group_id_f7bf68b7_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `grupos` (`id`),
  CONSTRAINT `usuarios_grupos_usuario_id_72c46a6b_fk_usuarios_id` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `usuarios_grupos`
--

LOCK TABLES `usuarios_grupos` WRITE;
/*!40000 ALTER TABLE `usuarios_grupos` DISABLE KEYS */;
/*!40000 ALTER TABLE `usuarios_grupos` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `usuarios_permisos`
--

DROP TABLE IF EXISTS `usuarios_permisos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `usuarios_permisos` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `usuario_id` bigint NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `usuarios_permisos_usuario_id_permission_id_85b53a8b_uniq` (`usuario_id`,`permission_id`),
  KEY `usuarios_permisos_permission_id_6e69ac22_fk_auth_permission_id` (`permission_id`),
  CONSTRAINT `usuarios_permisos_permission_id_6e69ac22_fk_auth_permission_id` FOREIGN KEY (`permission_id`) REFERENCES `permisos` (`id`),
  CONSTRAINT `usuarios_permisos_usuario_id_4cb02bdc_fk_usuarios_id` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `usuarios_permisos`
--

LOCK TABLES `usuarios_permisos` WRITE;
/*!40000 ALTER TABLE `usuarios_permisos` DISABLE KEYS */;
INSERT INTO `usuarios_permisos` VALUES (2,2,21),(1,2,24),(3,3,1),(4,3,2),(5,3,3),(6,3,4),(7,3,5),(8,3,6),(9,3,7),(10,3,8),(11,3,9),(12,3,10),(13,3,11),(14,3,12),(15,3,13),(16,3,14),(17,3,15),(18,3,16),(19,3,17),(20,3,18),(21,3,19),(22,3,20),(23,3,21),(24,3,22),(25,3,23),(26,3,24);
/*!40000 ALTER TABLE `usuarios_permisos` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-08-22 13:57:48
